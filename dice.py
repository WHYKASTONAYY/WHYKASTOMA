import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import sqlite3
from database import user_exists, get_user_balance, update_user_balance
from utils import send_with_retry, logger

# Evaluate each round with rolls in scoreboard
async def evaluate_round(game, chat_id, game_key, context):
    rolls1, rolls2 = game['rolls']['player1'], game['rolls']['player2']
    required_rolls = game['rolls_needed']
    logger.info(f"Evaluating round: Player1 rolls: {rolls1}, Player2 rolls: {rolls2}, Needed: {required_rolls}")

    if len(rolls1) < required_rolls or len(rolls2) < required_rolls:
        logger.error(f"Incomplete rolls: Player1: {len(rolls1)}, Player2: {len(rolls2)}")
        await send_with_retry(context.bot, chat_id, text="Error: Rolls incomplete. Please start the game again.")
        game['rolls'] = {'player1': [], 'player2': []}
        game['roll_count'] = {'player1': 0, 'player2': 0}
        game['current_player'] = 'player1'
        return

    if game['mode'] == 'normal':
        score1, score2 = rolls1[0], rolls2[0]
    elif game['mode'] == 'double':
        score1, score2 = sum(rolls1), sum(rolls2)
    else:  # crazy
        score1, score2 = 7 - rolls1[0], 7 - rolls2[0]

    if score1 > score2:
        game['scores']['player1'] += 1
    elif score2 > score1:
        game['scores']['player2'] += 1

    player1_username = (await context.bot.get_chat_member(chat_id, game['player1'])).user.username or "Player1"
    player2_username = "Bot" if game['player2'] == 'bot' else (await context.bot.get_chat_member(chat_id, game['player2'])).user.username or "Player2"

    text = (
        f"🎲 Round Results\n"
        f"@{player1_username} rolled: {', '.join(map(str, rolls1))}\n"
        f"{'Bot' if game['player2'] == 'bot' else '@' + player2_username} rolled: {', '.join(map(str, rolls2))}\n\n"
        f"🎲 Scoreboard\n"
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
            f"🎲 Final Round Results\n"
            f"@{player1_username} rolled: {', '.join(map(str, rolls1))}\n"
            f"{'Bot' if game['player2'] == 'bot' else '@' + player2_username} rolled: {', '.join(map(str, rolls2))}\n\n"
            f"🎲 Final Scoreboard\n"
            f"@{player1_username}: {game['scores']['player1']}\n"
            f"{'Bot' if game['player2'] == 'bot' else '@' + player2_username}: {game['scores']['player2']}\n\n"
            f"🏆 Game over!\n"
            f"{'Bot wins! You lost $' + str(game['bet']) + '.' if winner_id == 'bot' else '🎉 @' + winner_username + ' wins $' + str(prize) + '!'}"
        )
        keyboard = [
            [InlineKeyboardButton("Play Again", callback_data="dice_play_again"),
             InlineKeyboardButton("Double", callback_data="dice_double")]
        ]
        await send_with_retry(context.bot, chat_id, text=text, reply_markup=InlineKeyboardMarkup(keyboard))
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
        text += f"\n\nRound {game['round_number']}: @{player1_username}, your turn! Tap the button to roll the dice."
        keyboard = [[InlineKeyboardButton(f"🎲 Roll Dice (Round {game['round_number']})", callback_data=f"dice_roll_{game['round_number']}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_with_retry(context.bot, chat_id, text=text, reply_markup=reply_markup)

# Command handler for /dice
async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    args = context.args

    if not user_exists(user_id):
        await send_with_retry(context.bot, chat_id, text="Please register with /start.")
        return

    if 'bet_amount' not in context.user_data:
        await send_with_retry(context.bot, chat_id, text="Please use /dice <amount> to set a bet.")
        return

    try:
        amount = float(context.user_data['bet_amount'])
        if amount <= 0:
            raise ValueError("Bet must be positive.")
        balance = get_user_balance(user_id)
        if amount > balance:
            await send_with_retry(context.bot, chat_id, text=f"Insufficient balance! You have ${balance:.2f}.")
            return
        if (chat_id, user_id) in context.bot_data.get('user_games', {}):
            await send_with_retry(context.bot, chat_id, text="You are already in a game!")
            return
        context.user_data['dice_bet'] = amount
        context.user_data['dice_initiator'] = user_id

        keyboard = [
            [InlineKeyboardButton("🎲 Normal Mode", callback_data="dice_mode_normal")],
            [InlineKeyboardButton("🎲 Double Roll", callback_data="dice_mode_double")],
            [InlineKeyboardButton("🎲 Crazy Mode", callback_data="dice_mode_crazy")],
            [InlineKeyboardButton("ℹ️ Mode Guide", callback_data="dice_mode_guide"),
             InlineKeyboardButton("❌ Cancel", callback_data="dice_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_with_retry(context.bot, chat_id, text="🎲 Choose the game mode:", reply_markup=reply_markup)

    except ValueError as e:
        await send_with_retry(context.bot, chat_id, text=f"Invalid bet amount: {str(e)}. Use a positive number.")

# Start game against bot
async def start_game_against_bot(context, chat_id, user_id):
    if (chat_id, user_id) in context.bot_data.get('user_games', {}):
        await send_with_retry(context.bot, chat_id, text="You are already in a game!")
        return
    bet = context.user_data['dice_bet']
    mode = context.user_data['dice_mode']
    points = context.user_data['dice_points']
    game_key = (chat_id, user_id, 'bot')
    context.bot_data.setdefault('games', {})[game_key] = {
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
        'round_number': 1
    }
    context.bot_data.setdefault('user_games', {})[(chat_id, user_id)] = game_key
    update_user_balance(user_id, get_user_balance(user_id) - bet)
    player1_username = (await context.bot.get_chat_member(chat_id, user_id)).user.username or "Player1"
    text = (
        f"🎲 Match started!\n"
        f"Player 1: @{player1_username}\n"
        f"Player 2: Bot\n\n"
        f"Round 1: @{player1_username}, your turn! Tap the button to roll the dice."
    )
    keyboard = [[InlineKeyboardButton("🎲 Roll Dice (Round 1)", callback_data="dice_roll_1")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_with_retry(context.bot, chat_id, text=text, reply_markup=reply_markup)

# Button handler for dice game
async def dice_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data = query.data
    logger.info(f"Received callback data: {data}")  # Added for debugging

    if data == "dice_mode_guide":
        guide_text = (
            "🎲 **Normal Mode**: Roll one die, highest number wins the round.\n\n"
            "🎲 **Double Roll**: Roll two dice, highest sum wins the round.\n\n"
            "🎲 **Crazy Mode**: Roll one die, lowest number (inverted: 6=1, 1=6) wins the round."
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="dice_back")]]
        await query.edit_message_text(guide_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    elif data == "dice_back":
        keyboard = [
            [InlineKeyboardButton("🎲 Normal Mode", callback_data="dice_mode_normal")],
            [InlineKeyboardButton("🎲 Double Roll", callback_data="dice_mode_double")],
            [InlineKeyboardButton("🎲 Crazy Mode", callback_data="dice_mode_crazy")],
            [InlineKeyboardButton("ℹ️ Mode Guide", callback_data="dice_mode_guide"),
             InlineKeyboardButton("❌ Cancel", callback_data="dice_cancel")]
        ]
        await query.edit_message_text("🎲 Choose the game mode:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif data == "dice_cancel":
        if 'dice_initiator' in context.user_data and context.user_data['dice_initiator'] == user_id:
            context.user_data.clear()
            await query.edit_message_text("❌ Game setup cancelled.")
        return

    elif data.startswith("dice_mode_"):
        if 'dice_initiator' not in context.user_data or context.user_data['dice_initiator'] != user_id:
            return
        mode = data.split('_')[2]
        context.user_data['dice_mode'] = mode
        keyboard = [
            [InlineKeyboardButton("🏆 First to 1 point", callback_data="dice_points_1")],
            [InlineKeyboardButton("🏅 First to 2 points", callback_data="dice_points_2")],
            [InlineKeyboardButton("🥇 First to 3 points", callback_data="dice_points_3")],
            [InlineKeyboardButton("❌ Cancel", callback_data="dice_cancel")]
        ]
        await query.edit_message_text("🎲 Choose points to win:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("dice_points_"):
        if 'dice_initiator' not in context.user_data or context.user_data['dice_initiator'] != user_id:
            return
        points = int(data.split('_')[2])
        context.user_data['dice_points'] = points
        bet = context.user_data['dice_bet']
        mode = context.user_data['dice_mode'].capitalize()
        text = (
            f"🎲 **Game confirmation**\n"
            f"Game: Dice 🎲\n"
            f"First to {points} points\n"
            f"Mode: {mode} Mode\n"
            f"Your bet: ${bet:.2f}\n"
            f"Win multiplier: 1.92x"
        )
        keyboard = [
            [InlineKeyboardButton("✅ Confirm", callback_data="dice_confirm_setup"),
             InlineKeyboardButton("❌ Cancel", callback_data="dice_cancel")]
        ]
        await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "dice_confirm_setup":
        if 'dice_initiator' not in context.user_data or context.user_data['dice_initiator'] != user_id:
            return
        bet = context.user_data['dice_bet']
        mode = context.user_data['dice_mode'].capitalize()
        points = context.user_data['dice_points']
        username = (await context.bot.get_chat_member(chat_id, user_id)).user.username or "Someone"
        mode_description = {
            "normal": "Roll one die, highest number wins the round.",
            "double": "Roll two dice, highest sum wins the round.",
            "crazy": "Roll one die, lowest number (inverted: 6=1, 1=6) wins the round."
        }
        text = (
            f"🎲 {username} wants to play Dice!\n\n"
            f"Bet: ${bet:.2f}\n"
            f"Win multiplier: 1.92x\n"
            f"Mode: First to {points} points\n\n"
            f"{mode} Mode: {mode_description[context.user_data['dice_mode']]}"
        )
        keyboard = [
            [InlineKeyboardButton("🤝 Challenge a Player", callback_data="dice_challenge")],
            [InlineKeyboardButton("🤖 Play against Bot", callback_data="dice_bot")]
        ]
        await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "dice_challenge":
        if 'dice_initiator' not in context.user_data or context.user_data['dice_initiator'] != user_id:
            return
        context.user_data['expecting_username'] = True
        await send_with_retry(context.bot, chat_id, text="Enter the username of the player you want to challenge (e.g., @username):")

    elif data == "dice_bot":
        await start_game_against_bot(context, chat_id, user_id)

    elif data.startswith("dice_accept_"):
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
        context.bot_data.setdefault('games', {})[game_key] = {
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
            'round_number': 1
        }
        context.bot_data.setdefault('user_games', {})[(chat_id, game['initiator'])] = game_key
        context.bot_data['user_games'][(chat_id, user_id)] = game_key
        update_user_balance(game['initiator'], get_user_balance(game['initiator']) - game['bet'])
        update_user_balance(user_id, get_user_balance(user_id) - game['bet'])
        player1_username = (await context.bot.get_chat_member(chat_id, game['initiator'])).user.username or "Player1"
        player2_username = (await context.bot.get_chat_member(chat_id, user_id)).user.username or "Player2"
        text = (
            f"🎲 Match started!\n"
            f"Player 1: @{player1_username}\n"
            f"Player 2: @{player2_username}\n\n"
            f"Round 1: @{player1_username}, your turn! Tap the button to roll the dice."
        )
        keyboard = [[InlineKeyboardButton("🎲 Roll Dice (Round 1)", callback_data="dice_roll_1")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_with_retry(context.bot, chat_id, text=text, reply_markup=reply_markup)

    elif data.startswith("dice_cancel_"):
        game_id = int(data.split('_')[2])
        if game_id not in context.bot_data.get('pending_challenges', {}):
            await query.edit_message_text("❌ Challenge no longer valid.")
            return
        game = context.bot_data['pending_challenges'][game_id]
        initiator_username = (await context.bot.get_chat_member(chat_id, game['initiator'])).user.username or "Someone"
        text = f"❌ {initiator_username}'s challenge was declined."
        await query.edit_message_text(text=text)
        del context.bot_data['pending_challenges'][game_id]

    elif data.startswith("dice_roll_"):
        logger.info(f"Roll dice pressed by user {user_id} in chat {chat_id}")
        game_key = context.bot_data.get('user_games', {}).get((chat_id, user_id))
        if not game_key:
            logger.info("No game key found")
            await send_with_retry(context.bot, chat_id, text="No active game found!")
            return
        game = context.bot_data.get('games', {}).get(game_key)
        if not game:
            logger.info("Game not found in bot_data")
            await send_with_retry(context.bot, chat_id, text="Game data missing!")
            return
        if max(game['scores'].values()) >= game['points_to_win']:
            await send_with_retry(context.bot, chat_id, text="The game has already ended!")
            return
        player_key = 'player1' if game['player1'] == user_id else 'player2' if game['player2'] == user_id else None
        if not player_key:
            logger.info("User is not a player in this game")
            return
        try:
            turn_round = int(data.split('_')[2])
        except ValueError:
            await send_with_retry(context.bot, chat_id, text="Invalid callback data.")
            return
        if turn_round != game['round_number']:
            await send_with_retry(context.bot, chat_id, text="This button is from a previous round!")
            return
        if player_key != game['current_player']:
            logger.info(f"User {player_key} is not the current player ({game['current_player']})")
            await send_with_retry(context.bot, chat_id, text="It's not your turn!")
            return
        logger.info(f"Game state before roll: {game}")
        dice_msg = await send_with_retry(context.bot, chat_id, emoji='🎲')
        if dice_msg is None:
            await send_with_retry(context.bot, chat_id, text="Failed to roll the dice. Please try again later.")
            return
        await asyncio.sleep(4)  # Wait for dice animation
        dice_value = dice_msg.dice.value
        game['rolls'][player_key].append(dice_value)
        game['roll_count'][player_key] += 1
        logger.info(f"Player {player_key} rolled: {dice_value}, Rolls: {game['rolls'][player_key]}")

        if game['roll_count']['player1'] == game['rolls_needed'] and game['roll_count']['player2'] == game['rolls_needed']:
            await evaluate_round(game, chat_id, game_key, context)
        else:
            if game['roll_count'][player_key] < game['rolls_needed']:
                keyboard = [[InlineKeyboardButton(f"🎲 Roll Again (Round {game['round_number']})", callback_data=f"dice_roll_{game['round_number']}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await send_with_retry(context.bot, chat_id, text=f"Round {game['round_number']}: Roll again!", reply_markup=reply_markup)
            else:
                other_player = 'player2' if player_key == 'player1' else 'player1'
                game['current_player'] = other_player
                if game[other_player] == 'bot':
                    bot_rolls = []
                    for _ in range(game['rolls_needed'] - game['roll_count'][other_player]):
                        dice_msg = await send_with_retry(context.bot, chat_id, emoji='🎲')
                        if dice_msg is None:
                            await send_with_retry(context.bot, chat_id, text="Failed to roll the dice for the bot. Please try again later.")
                            return
                        await asyncio.sleep(4)
                        bot_rolls.append(dice_msg.dice.value)
                    game['rolls'][other_player].extend(bot_rolls)
                    game['roll_count'][other_player] += len(bot_rolls)
                    logger.info(f"Bot rolled: {bot_rolls}, Game state: {game}")
                    await evaluate_round(game, chat_id, game_key, context)
                else:
                    other_username = (await context.bot.get_chat_member(chat_id, game[other_player])).user.username or "Player"
                    keyboard = [[InlineKeyboardButton(f"🎲 Roll Dice (Round {game['round_number']})", callback_data=f"dice_roll_{game['round_number']}")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await send_with_retry(context.bot, chat_id, text=f"Round {game['round_number']}: @{other_username}, your turn! Tap the button to roll the dice.", reply_markup=reply_markup)

    elif data == "dice_play_again":
        last_games = context.bot_data.get('last_games', {}).get(chat_id, {})
        last_game = last_games.get(user_id)
        if not last_game:
            await send_with_retry(context.bot, chat_id, text="No previous game found.")
            return
        opponent = last_game['opponent']
        if opponent == 'bot':
            context.user_data['dice_mode'] = last_game['mode']
            context.user_data['dice_points'] = last_game['points_to_win']
            context.user_data['dice_bet'] = last_game['bet']
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
                f"🎲 {initiator_username} wants to play again with the same settings!\n"
                f"Bet: ${last_game['bet']:.2f}\n"
                f"Mode: {last_game['mode'].capitalize()}\n"
                f"First to {last_game['points_to_win']} points\n\n"
                f"@{opponent_username}, do you accept?"
            )
            keyboard = [
                [InlineKeyboardButton("Accept", callback_data=f"dice_accept_{game_id}"),
                 InlineKeyboardButton("Cancel", callback_data=f"dice_cancel_{game_id}")]
            ]
            await send_with_retry(context.bot, chat_id, text=text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "dice_double":
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
            context.user_data['dice_mode'] = last_game['mode']
            context.user_data['dice_points'] = last_game['points_to_win']
            context.user_data['dice_bet'] = new_bet
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
                f"🎲 {initiator_username} wants to double the bet and play again!\n"
                f"Bet: ${new_bet:.2f}\n"
                f"Mode: {last_game['mode'].capitalize()}\n"
                f"First to {last_game['points_to_win']} points\n\n"
                f"@{opponent_username}, do you accept?"
            )
            keyboard = [
                [InlineKeyboardButton("Accept", callback_data=f"dice_accept_{game_id}"),
                 InlineKeyboardButton("Cancel", callback_data=f"dice_cancel_{game_id}")]
            ]
            await send_with_retry(context.bot, chat_id, text=text, reply_markup=InlineKeyboardMarkup(keyboard))

# Text handler for username input in dice game
async def dice_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if context.user_data.get('expecting_username') and context.user_data.get('dice_initiator') == user_id:
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
        if get_user_balance(challenged_user_id) < context.user_data['dice_bet']:
            await send_with_retry(context.bot, chat_id, text=f"@{username} doesn’t have enough balance!")
            return
        if (chat_id, challenged_user_id) in context.bot_data.get('user_games', {}):
            await send_with_retry(context.bot, chat_id, text=f"@{username} is already in a game!")
            return
        game_id = len(context.bot_data.get('pending_challenges', {})) + 1
        context.bot_data.setdefault('pending_challenges', {})[game_id] = {
            'initiator': user_id,
            'challenged': challenged_user_id,
            'mode': context.user_data['dice_mode'],
            'points_to_win': context.user_data['dice_points'],
            'bet': context.user_data['dice_bet']
        }
        initiator_username = (await context.bot.get_chat_member(chat_id, user_id)).user.username or "Someone"
        text = (
            f"🎲 {initiator_username} challenges {username}!\n"
            f"Bet: ${context.user_data['dice_bet']:.2f}\n"
            f"Mode: {context.user_data['dice_mode'].capitalize()}\n"
            f"First to {context.user_data['dice_points']} points"
        )
        keyboard = [
            [InlineKeyboardButton("Accept", callback_data=f"dice_accept_{game_id}"),
             InlineKeyboardButton("Cancel", callback_data=f"dice_cancel_{game_id}")]
        ]
        await send_with_retry(context.bot, chat_id, text=text, reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data['expecting_username'] = False
