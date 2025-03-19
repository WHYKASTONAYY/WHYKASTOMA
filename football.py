import logging
import asyncio
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import user_exists, get_user_balance, update_user_balance
from utils import send_with_retry, logger

# Helper function to calculate effective score based on mode
def calculate_effective_score(rolls, mode):
    """Calculate the effective score based on the game mode."""
    if mode == 'normal':
        return rolls[0] if rolls[0] >= 3 else 0
    elif mode == 'double':
        return sum(roll for roll in rolls if roll >= 3)
    elif mode == 'crazy':
        return 1 if rolls[0] == 1 else 0  # Rolling a 1 wins in crazy mode

# Evaluate each round
async def evaluate_round(game, chat_id, game_key, context):
    rolls1, rolls2 = game['rolls']['player1'], game['rolls']['player2']
    required_rolls = game['rolls_needed']
    logger.info(f"Evaluating round - Mode: {game['mode']}, Player1 rolls: {rolls1}, Player2 rolls: {rolls2}, Needed: {required_rolls}")

    if len(rolls1) < required_rolls or len(rolls2) < required_rolls:
        logger.error(f"Incomplete rolls: Player1: {len(rolls1)}, Player2: {len(rolls2)}")
        await send_with_retry(context.bot, chat_id, text="Error: Shots incomplete. Please start the game again.")
        game['rolls'] = {'player1': [], 'player2': []}
        game['roll_count'] = {'player1': 0, 'player2': 0}
        game['current_player'] = 'player1'
        return

    # Calculate effective scores
    effective_score1 = calculate_effective_score(rolls1, game['mode'])
    effective_score2 = calculate_effective_score(rolls2, game['mode'])

    logger.info(f"Effective scores - Player1: {effective_score1}, Player2: {effective_score2}")

    # Award points only if one player scores and the other doesn't
    if effective_score1 > 0 and effective_score2 == 0:
        game['scores']['player1'] += 1
        logger.info("Player1 scored")
    elif effective_score2 > 0 and effective_score1 == 0:
        game['scores']['player2'] += 1
        logger.info("Player2 scored")
    else:
        logger.info("No points awarded - both scored or both missed")

    player1_username = (await context.bot.get_chat_member(chat_id, game['player1'])).user.username or "Player1"
    player2_username = "Bot" if game['player2'] == 'bot' else (await context.bot.get_chat_member(chat_id, game['player2'])).user.username or "Player2"

    text = (
        f"⚽ Round Results\n"
        f"⚽ Scoreboard\n"
        f"@{player1_username}: {game['scores']['player1']}\n"
        f"{'Bot' if game['player2'] == 'bot' else '@' + player2_username}: {game['scores']['player2']}"
    )

    if max(game['scores'].values()) >= game['points_to_win']:
        winner = 'player1' if game['scores']['player1'] > game['scores']['player2'] else 'player2'
        winner_id = game[winner]
        prize = game['bet'] * 1.92
        if winner_id != 'bot':
            update_user_balance(winner_id, get_user_balance(winner_id) + prize + game['bet'])
        winner_username = player1_username if winner == 'player1' else player2_username
        text = (
            f"⚽ Final Round Results\n"
            f"⚽ Final Scoreboard\n"
            f"@{player1_username}: {game['scores']['player1']}\n"
            f"{'Bot' if game['player2'] == 'bot' else '@' + player2_username}: {game['scores']['player2']}\n\n"
            f"🏆 Game over!\n"
            f"{'Bot wins! You lost $' + str(game['bet']) + '.' if winner_id == 'bot' else '🎉 @' + winner_username + ' wins $' + str(prize) + '!'}"
        )
        keyboard = [
            [InlineKeyboardButton("Play Again", callback_data="football_play_again"),
             InlineKeyboardButton("Double", callback_data="football_double")]
        ]
        await send_with_retry(context.bot, chat_id, text, reply_markup=InlineKeyboardMarkup(keyboard))
        if game['player2'] != 'bot':
            last_game_p1 = {
                'opponent': game['player2'],
                'mode': game['mode'],
                'points_to_win': game['points_to_win'],
                'bet': game['bet']
            }
            last_game_p2 = {
                'opponent': game['player1'],
                'mode': game['mode'],
                'points_to_win': game['points_to_win'],
                'bet': game['bet']
            }
            context.bot_data.setdefault('last_games', {}).setdefault(chat_id, {})[game['player1']] = last_game_p1
            context.bot_data['last_games'][chat_id][game['player2']] = last_game_p2
        else:
            last_game = {
                'opponent': 'bot',
                'mode': game['mode'],
                'points_to_win': game['points_to_win'],
                'bet': game['bet']
            }
            context.bot_data.setdefault('last_games', {}).setdefault(chat_id, {})[game['player1']] = last_game
        if game['player2'] != 'bot':
            del context.bot_data['user_games'][(chat_id, game['player2'])]
        del context.bot_data['user_games'][(chat_id, game['player1'])]
        del context.bot_data['games'][game_key]
    else:
        game['rolls'] = {'player1': [], 'player2': []}
        game['roll_count'] = {'player1': 0, 'player2': 0}
        game['current_player'] = 'player1'
        game['round_number'] += 1
        text += f"\n\nRound {game['round_number']}: @{player1_username}, your turn! Tap the button to take a shot."
        keyboard = [[InlineKeyboardButton(f"⚽ Take a Shot (Round {game['round_number']})", callback_data=f"football_take_shot_{game['round_number']}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = await send_with_retry(context.bot, chat_id, text, reply_markup=reply_markup)
        game['message_id'] = message.message_id  # Update message_id for the new round

# Command handler for /football
async def football_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    args = context.args

    if not user_exists(user_id):
        await send_with_retry(context.bot, chat_id, text="Please register with /start.")
        return

    if len(args) != 1:
        await send_with_retry(context.bot, chat_id, text="Usage: /football <amount>\nExample: /football 1")
        return

    try:
        amount = float(args[0])
        if amount <= 0:
            raise ValueError("Bet must be positive.")
        balance = get_user_balance(user_id)
        if amount > balance:
            await send_with_retry(context.bot, chat_id, text=f"Insufficient balance! You have ${balance:.2f}.")
            return
        if (chat_id, user_id) in context.bot_data.get('user_games', {}):
            await send_with_retry(context.bot, chat_id, text="You are already in a game!")
            return

        # Initialize setup state with message_id placeholder
        setup = {
            'initiator': user_id,
            'bet': amount,
            'state': 'mode_selection',
            'message_id': None
        }
        context.user_data['football_setup'] = setup

        keyboard = [
            [InlineKeyboardButton("⚽ Normal Mode", callback_data="football_mode_normal")],
            [InlineKeyboardButton("⚽ Double Shot", callback_data="football_mode_double")],
            [InlineKeyboardButton("⚽ Crazy Mode", callback_data="football_mode_crazy")],
            [InlineKeyboardButton("ℹ️ Mode Guide", callback_data="football_mode_guide"),
             InlineKeyboardButton("❌ Cancel", callback_data="football_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = await send_with_retry(context.bot, chat_id, text="⚽ Choose the game mode:", reply_markup=reply_markup)
        setup['message_id'] = message.message_id  # Store the message_id for setup

    except ValueError as e:
        await send_with_retry(context.bot, chat_id, text=f"Invalid bet amount: {str(e)}. Use a positive number.")

# Start game against bot
async def start_game_against_bot(context, chat_id, user_id):
    if (chat_id, user_id) in context.bot_data.get('user_games', {}):
        await send_with_retry(context.bot, chat_id, text="You are already in a game!")
        return
    setup = context.user_data.get('football_setup', {})
    bet = setup['bet']
    mode = context.user_data['football_mode']
    points = context.user_data['football_points']
    game_key = (chat_id, user_id, 'bot')
    game = {
        'player1': user_id,
        'player2': 'bot',
        'mode': mode,
        'points_to_win': points,
        'bet': bet,
        'scores': {'player1': 0, 'player2': 0},
        'current_player': 'player1',
        'rolls': {'player1': [], 'player2': []},
        'rolls_needed': 2 if mode == 'double' else 1,
        'roll_count': {'player1': 0, 'player2': 0},
        'round_number': 1,
        'message_id': None
    }
    context.bot_data.setdefault('games', {})[game_key] = game
    context.bot_data.setdefault('user_games', {})[(chat_id, user_id)] = game_key
    update_user_balance(user_id, get_user_balance(user_id) - bet)
    player1_username = (await context.bot.get_chat_member(chat_id, user_id)).user.username or "Player1"
    text = (
        f"⚽ Match started!\n"
        f"Player 1: @{player1_username}\n"
        f"Player 2: Bot\n\n"
        f"Round 1: @{player1_username}, your turn! Tap the button to take a shot."
    )
    keyboard = [[InlineKeyboardButton("⚽ Take a Shot (Round 1)", callback_data="football_take_shot_1")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = await send_with_retry(context.bot, chat_id, text, reply_markup=reply_markup)
    game['message_id'] = message.message_id  # Store the game message_id
    context.user_data.pop('football_setup', None)  # Clear setup state

# Button handler for football game
async def football_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data = query.data

    try:
        # Handle setup phase
        if 'football_setup' in context.user_data:
            setup = context.user_data['football_setup']
            if setup['initiator'] != user_id or setup['message_id'] != query.message.message_id:
                await query.answer("This is not your game setup!")
                return

            if data == "football_mode_guide":
                guide_text = (
                    "⚽ **Normal Mode**: Take one shot, highest number wins the round.\n\n"
                    "⚽ **Double Shot**: Take two shots, highest sum wins the round.\n\n"
                    "⚽ **Crazy Mode**: Take one shot, rolling a 1 wins the round."
                )
                keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="football_back")]]
                await query.edit_message_text(guide_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
                return

            elif data == "football_back":
                keyboard = [
                    [InlineKeyboardButton("⚽ Normal Mode", callback_data="football_mode_normal")],
                    [InlineKeyboardButton("⚽ Double Shot", callback_data="football_mode_double")],
                    [InlineKeyboardButton("⚽ Crazy Mode", callback_data="football_mode_crazy")],
                    [InlineKeyboardButton("ℹ️ Mode Guide", callback_data="football_mode_guide"),
                     InlineKeyboardButton("❌ Cancel", callback_data="football_cancel")]
                ]
                await query.edit_message_text("⚽ Choose the game mode:", reply_markup=InlineKeyboardMarkup(keyboard))
                return

            elif data == "football_cancel":
                context.user_data.pop('football_setup', None)
                await query.edit_message_text("❌ Game setup cancelled.")
                return

            elif data.startswith("football_mode_"):
                mode = data.split('_')[2]
                context.user_data['football_mode'] = mode
                keyboard = [
                    [InlineKeyboardButton("🏆 First to 1 point", callback_data="football_points_1")],
                    [InlineKeyboardButton("🏅 First to 2 points", callback_data="football_points_2")],
                    [InlineKeyboardButton("🥇 First to 3 points", callback_data="football_points_3")],
                    [InlineKeyboardButton("❌ Cancel", callback_data="football_cancel")]
                ]
                await query.edit_message_text("⚽ Choose points to win:", reply_markup=InlineKeyboardMarkup(keyboard))

            elif data.startswith("football_points_"):
                points = int(data.split('_')[2])
                context.user_data['football_points'] = points
                bet = setup['bet']
                mode = context.user_data['football_mode'].capitalize()
                text = (
                    f"⚽ **Game confirmation**\n"
                    f"Game: Football ⚽\n"
                    f"First to {points} points\n"
                    f"Mode: {mode} Mode\n"
                    f"Your bet: ${bet:.2f}\n"
                    f"Win multiplier: 1.92x"
                )
                keyboard = [
                    [InlineKeyboardButton("✅ Confirm", callback_data="football_confirm_setup"),
                     InlineKeyboardButton("❌ Cancel", callback_data="football_cancel")]
                ]
                await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

            elif data == "football_confirm_setup":
                bet = setup['bet']
                mode = context.user_data['football_mode'].capitalize()
                points = context.user_data['football_points']
                username = (await context.bot.get_chat_member(chat_id, user_id)).user.username or "Someone"
                mode_description = {
                    "normal": "Take one shot, highest number wins the round.",
                    "double": "Take two shots, highest sum wins the round.",
                    "crazy": "Take one shot, rolling a 1 wins the round."
                }
                text = (
                    f"⚽ {username} wants to play Football!\n\n"
                    f"Bet: ${bet:.2f}\n"
                    f"Win multiplier: 1.92x\n"
                    f"Mode: First to {points} points\n\n"
                    f"{mode} Mode: {mode_description[context.user_data['football_mode']]}"
                )
                keyboard = [
                    [InlineKeyboardButton("🤝 Challenge a Player", callback_data="football_challenge")],
                    [InlineKeyboardButton("🤖 Play against Bot", callback_data="football_bot")]
                ]
                await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard))

            elif data == "football_challenge":
                context.user_data['expecting_username'] = True
                await send_with_retry(context.bot, chat_id, text="Enter the username of the player you want to challenge (e.g., @username):")

            elif data == "football_bot":
                await start_game_against_bot(context, chat_id, user_id)

        # Handle in-game phase
        elif data.startswith("football_take_shot_"):
            game_key = context.bot_data.get('user_games', {}).get((chat_id, user_id))
            if not game_key:
                await query.answer("No active game found!")
                return
            game = context.bot_data.get('games', {}).get(game_key)
            if not game or query.message.message_id != game.get('message_id'):
                await query.answer("This button is from an old message!")
                return
            if max(game['scores'].values()) >= game['points_to_win']:
                await send_with_retry(context.bot, chat_id, text="The game has already ended!")
                return
            player_key = 'player1' if game['player1'] == user_id else 'player2' if game['player2'] == user_id else None
            if not player_key:
                return
            turn_round = int(data.split('_')[3])
            if turn_round != game['round_number']:
                await send_with_retry(context.bot, chat_id, text="This button is from a previous round!")
                return
            if player_key != game['current_player']:
                await send_with_retry(context.bot, chat_id, text="It's not your turn!")
                return
            shot_msg = await send_with_retry(context.bot, chat_id, emoji='⚽')
            if shot_msg is None:
                await send_with_retry(context.bot, chat_id, text="Failed to take a shot. Please try again later.")
                return
            shot_value = shot_msg.dice.value
            game['rolls'][player_key].append(shot_value)
            game['roll_count'][player_key] += 1
            logger.info(f"Player {player_key} rolled: {shot_value}, Rolls: {game['rolls'][player_key]}, Count: {game['roll_count'][player_key]}")
            await asyncio.sleep(2)  # Delay after player's shot for thrill

            if game['roll_count'][player_key] < game['rolls_needed']:
                keyboard = [[InlineKeyboardButton(f"⚽ Take Another Shot (Round {game['round_number']})", callback_data=f"football_take_shot_{game['round_number']}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                message = await send_with_retry(context.bot, chat_id, text=f"Round {game['round_number']}: Take another shot!", reply_markup=reply_markup)
                game['message_id'] = message.message_id  # Update message_id
            else:
                other_player = 'player2' if player_key == 'player1' else 'player1'
                game['current_player'] = other_player
                if game[other_player] == 'bot':
                    bot_rolls = []
                    for _ in range(game['rolls_needed'] - game['roll_count'][other_player]):
                        shot_msg = await send_with_retry(context.bot, chat_id, emoji='⚽')
                        if shot_msg is None:
                            await send_with_retry(context.bot, chat_id, text="Failed to take a shot for the bot. Please try again later.")
                            return
                        bot_rolls.append(shot_msg.dice.value)
                    game['rolls'][other_player].extend(bot_rolls)
                    game['roll_count'][other_player] += len(bot_rolls)
                    logger.info(f"Bot rolled: {bot_rolls}, Rolls: {game['rolls'][other_player]}, Count: {game['roll_count'][other_player]}")
                    await asyncio.sleep(2)  # Delay after bot's shot for thrill

                if game['roll_count']['player1'] == game['rolls_needed'] and game['roll_count']['player2'] == game['rolls_needed']:
                    await asyncio.sleep(2)  # Suspenseful delay before revealing result
                    await evaluate_round(game, chat_id, game_key, context)
                else:
                    other_username = (await context.bot.get_chat_member(chat_id, game[other_player])).user.username or "Player"
                    keyboard = [[InlineKeyboardButton(f"⚽ Take a Shot (Round {game['round_number']})", callback_data=f"football_take_shot_{game['round_number']}")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    message = await send_with_retry(context.bot, chat_id, text=f"Round {game['round_number']}: @{other_username}, your turn! Tap the button to take a shot.", reply_markup=reply_markup)
                    game['message_id'] = message.message_id  # Update message_id

        # Handle post-game and challenge actions
        elif data.startswith("football_accept_"):
            game_id = int(data.split('_')[2])
            if game_id not in context.bot_data.get('pending_challenges', {}):
                await query.edit_message_text("❌ Challenge no longer valid.")
                return
            game = context.bot_data['pending_challenges'][game_id]
            if user_id != game['challenged']:
                return
            if (chat_id, game['initiator']) in context.bot_data.get('user_games', {}) or (chat_id, user_id) in context.bot_data.get('user_games', {}):
                await send_with_retry(context.bot, chat_id, text="One of you is already in a game!")
                return
            game_key = (chat_id, game['initiator'], user_id)
            game_state = {
                'player1': game['initiator'],
                'player2': user_id,
                'mode': game['mode'],
                'points_to_win': game['points_to_win'],
                'bet': game['bet'],
                'scores': {'player1': 0, 'player2': 0},
                'current_player': 'player1',
                'rolls': {'player1': [], 'player2': []},
                'rolls_needed': 2 if game['mode'] == 'double' else 1,
                'roll_count': {'player1': 0, 'player2': 0},
                'round_number': 1,
                'message_id': None
            }
            context.bot_data.setdefault('games', {})[game_key] = game_state
            context.bot_data.setdefault('user_games', {})[(chat_id, game['initiator'])] = game_key
            context.bot_data['user_games'][(chat_id, user_id)] = game_key
            update_user_balance(game['initiator'], get_user_balance(game['initiator']) - game['bet'])
            update_user_balance(user_id, get_user_balance(user_id) - game['bet'])
            player1_username = (await context.bot.get_chat_member(chat_id, game['initiator'])).user.username or "Player1"
            player2_username = (await context.bot.get_chat_member(chat_id, user_id)).user.username or "Player2"
            text = (
                f"⚽ Match started!\n"
                f"Player 1: @{player1_username}\n"
                f"Player 2: @{player2_username}\n\n"
                f"Round 1: @{player1_username}, your turn! Tap the button to take a shot."
            )
            keyboard = [[InlineKeyboardButton("⚽ Take a Shot (Round 1)", callback_data="football_take_shot_1")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = await send_with_retry(context.bot, chat_id, text, reply_markup=reply_markup)
            game_state['message_id'] = message.message_id  # Store the game message_id
            del context.bot_data['pending_challenges'][game_id]
            if 'football_setup' in context.user_data:
                del context.user_data['football_setup']

        elif data.startswith("football_cancel_"):
            game_id = int(data.split('_')[2])
            if game_id not in context.bot_data.get('pending_challenges', {}):
                await query.edit_message_text("❌ Challenge no longer valid.")
                return
            game = context.bot_data['pending_challenges'][game_id]
            initiator_username = (await context.bot.get_chat_member(chat_id, game['initiator'])).user.username or "Someone"
            text = f"❌ {initiator_username}'s challenge was declined."
            await query.edit_message_text(text=text)
            del context.bot_data['pending_challenges'][game_id]

        elif data == "football_play_again":
            last_games = context.bot_data.get('last_games', {}).get(chat_id, {})
            last_game = last_games.get(user_id)
            if not last_game:
                await send_with_retry(context.bot, chat_id, text="No previous game found.")
                return
            opponent = last_game['opponent']
            if opponent == 'bot':
                context.user_data['football_mode'] = last_game['mode']
                context.user_data['football_points'] = last_game['points_to_win']
                context.user_data['football_setup'] = {'initiator': user_id, 'bet': last_game['bet'], 'state': 'mode_selection', 'message_id': None}
                await start_game_against_bot(context, chat_id, user_id)
            else:
                opponent_id = opponent
                opponent_username = (await context.bot.get_chat_member(chat_id, opponent_id)).user.username or "Someone"
                if (chat_id, opponent_id) in context.bot_data.get('user_games', {}):
                    await send_with_retry(context.bot, chat_id, text=f"@{opponent_username} is already in a game!")
                    return
                game_id = len(context.bot_data.get('pending_challenges', {})) + 1
                context.bot_data.setdefault('pending_challenges', {})[game_id] = {
                    'initiator': user_id,
                    'challenged': opponent_id,
                    'mode': last_game['mode'],
                    'points_to_win': last_game['points_to_win'],
                    'bet': last_game['bet']
                }
                initiator_username = (await context.bot.get_chat_member(chat_id, user_id)).user.username or "Someone"
                text = (
                    f"⚽ {initiator_username} wants to play again with the same settings!\n"
                    f"Bet: ${last_game['bet']:.2f}\n"
                    f"Mode: {last_game['mode'].capitalize()}\n"
                    f"First to {last_game['points_to_win']} points\n\n"
                    f"@{opponent_username}, do you accept?"
                )
                keyboard = [
                    [InlineKeyboardButton("Accept", callback_data=f"football_accept_{game_id}"),
                     InlineKeyboardButton("Cancel", callback_data=f"football_cancel_{game_id}")]
                ]
                await send_with_retry(context.bot, chat_id, text, reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "football_double":
            last_games = context.bot_data.get('last_games', {}).get(chat_id, {})
            last_game = last_games.get(user_id)
            if not last_game:
                await send_with_retry(context.bot, chat_id, text="No previous game found.")
                return
            opponent = last_game['opponent']
            new_bet = last_game['bet'] * 2
            if opponent == 'bot':
                balance = get_user_balance(user_id)
                if new_bet > balance:
                    await send_with_retry(context.bot, chat_id, text=f"Insufficient balance! You need ${new_bet:.2f} but have ${balance:.2f}.")
                    return
                context.user_data['football_mode'] = last_game['mode']
                context.user_data['football_points'] = last_game['points_to_win']
                context.user_data['football_setup'] = {'initiator': user_id, 'bet': new_bet, 'state': 'mode_selection', 'message_id': None}
                await start_game_against_bot(context, chat_id, user_id)
            else:
                opponent_id = opponent
                initiator_balance = get_user_balance(user_id)
                opponent_balance = get_user_balance(opponent_id)
                if new_bet > initiator_balance or new_bet > opponent_balance:
                    await send_with_retry(context.bot, chat_id, text="One of you doesn’t have enough balance for the doubled bet!")
                    return
                if (chat_id, opponent_id) in context.bot_data.get('user_games', {}):
                    opponent_username = (await context.bot.get_chat_member(chat_id, opponent_id)).user.username or "Someone"
                    await send_with_retry(context.bot, chat_id, text=f"@{opponent_username} is already in a game!")
                    return
                game_id = len(context.bot_data.get('pending_challenges', {})) + 1
                context.bot_data.setdefault('pending_challenges', {})[game_id] = {
                    'initiator': user_id,
                    'challenged': opponent_id,
                    'mode': last_game['mode'],
                    'points_to_win': last_game['points_to_win'],
                    'bet': new_bet
                }
                initiator_username = (await context.bot.get_chat_member(chat_id, user_id)).user.username or "Someone"
                opponent_username = (await context.bot.get_chat_member(chat_id, opponent_id)).user.username or "Someone"
                text = (
                    f"⚽ {initiator_username} wants to double the bet and play again!\n"
                    f"Bet: ${new_bet:.2f}\n"
                    f"Mode: {last_game['mode'].capitalize()}\n"
                    f"First to {last_game['points_to_win']} points\n\n"
                    f"@{opponent_username}, do you accept?"
                )
                keyboard = [
                    [InlineKeyboardButton("Accept", callback_data=f"football_accept_{game_id}"),
                     InlineKeyboardButton("Cancel", callback_data=f"football_cancel_{game_id}")]
                ]
                await send_with_retry(context.bot, chat_id, text, reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Error in football_button_handler: {e}")
        await query.edit_message_text("An error occurred. Please try again.")

# Text handler for username input in football game
async def football_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if context.user_data.get('expecting_username') and context.user_data.get('football_setup', {}).get('initiator') == user_id:
        username = update.message.text.strip()
        if not username.startswith('@'):
            await send_with_retry(context.bot, chat_id, text="Invalid username. Use @username.")
            return
        username = username[1:]
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            c.execute("SELECT user_id FROM users WHERE username = ?", (username,))
            result = c.fetchone()
        if not result:
            await send_with_retry(context.bot, chat_id, text=f"User @{username} not found.")
            return
        challenged_user_id = result[0]
        if challenged_user_id == user_id:
            await send_with_retry(context.bot, chat_id, text="You can't challenge yourself!")
            return
        setup = context.user_data['football_setup']
        if get_user_balance(challenged_user_id) < setup['bet']:
            await send_with_retry(context.bot, chat_id, text=f"@{username} doesn’t have enough balance!")
            return
        if (chat_id, challenged_user_id) in context.bot_data.get('user_games', {}):
            await send_with_retry(context.bot, chat_id, text=f"@{username} is already in a game!")
            return
        game_id = len(context.bot_data.get('pending_challenges', {})) + 1
        context.bot_data.setdefault('pending_challenges', {})[game_id] = {
            'initiator': user_id,
            'challenged': challenged_user_id,
            'mode': context.user_data['football_mode'],
            'points_to_win': context.user_data['football_points'],
            'bet': setup['bet']
        }
        initiator_username = (await context.bot.get_chat_member(chat_id, user_id)).user.username or "Someone"
        text = (
            f"⚽ {initiator_username} challenges {username}!\n"
            f"Bet: ${setup['bet']:.2f}\n"
            f"Mode: {context.user_data['football_mode'].capitalize()}\n"
            f"First to {context.user_data['football_points']} points"
        )
        keyboard = [
            [InlineKeyboardButton("Accept", callback_data=f"football_accept_{game_id}"),
             InlineKeyboardButton("Cancel", callback_data=f"football_cancel_{game_id}")]
        ]
        await send_with_retry(context.bot, chat_id, text, reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data['expecting_username'] = False
