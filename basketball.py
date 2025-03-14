import logging
import asyncio
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import user_exists, get_user_balance, update_user_balance
from utils import send_with_retry, logger

# Helper function to calculate effective score
def calculate_effective_score(rolls, mode):
    """Calculate effective score based on game mode."""
    if mode == 'normal':
        return rolls[0] if rolls[0] >= 4 else 0  # Only rolls >= 4 count
    elif mode == 'double':
        return sum(roll for roll in rolls if roll >= 4)  # Sum of rolls >= 4
    elif mode == 'crazy':
        return 1 if rolls[0] == 1 else 0  # Rolling a 1 counts as a score

# Evaluate each round with updated scoring logic and transparency
async def evaluate_round(game, chat_id, game_key, context):
    shots1, shots2 = game['rolls']['player1'], game['rolls']['player2']
    required_shots = game['rolls_needed']
    logger.info(f"Evaluating round - Mode: {game['mode']}, Player1 shots: {shots1}, Player2 shots: {shots2}")

    if len(shots1) < required_shots or len(shots2) < required_shots:
        await send_with_retry(context.bot, chat_id, "Error: Shots incomplete. Please start again.")
        game['rolls'] = {'player1': [], 'player2': []}
        game['roll_count'] = {'player1': 0, 'player2': 0}
        game['current_player'] = 'player1'
        return

    # Calculate effective scores
    score1 = calculate_effective_score(shots1, game['mode'])
    score2 = calculate_effective_score(shots2, game['mode'])

    # Award points only if one player scores and the other does not
    if score1 > 0 and score2 == 0:
        game['scores']['player1'] += 1
    elif score2 > 0 and score1 == 0:
        game['scores']['player2'] += 1

    player1_username = (await context.bot.get_chat_member(chat_id, game['player1'])).user.username or "Player1"
    player2_username = "Bot" if game['player2'] == 'bot' else (await context.bot.get_chat_member(chat_id, game['player2'])).user.username or "Player2"

    # Round results with shots and scores for clarity
    text = (
        f"🏀 Round Results\n"
        f"Mode: {game['mode']}\n"
        f"@{player1_username} shots: {shots1}, score: {score1}\n"
        f"{'Bot' if game['player2'] == 'bot' else '@' + player2_username} shots: {shots2}, score: {score2}\n"
        f"🏀 Scoreboard\n"
        f"@{player1_username}: {game['scores']['player1']}\n"
        f"{'Bot' if game['player2'] == 'bot' else '@' + player2_username}: {game['scores']['player2']}"
    )

    # Explain point awarding
    if score1 > 0 and score2 == 0:
        text += f"\nPoint awarded to @{player1_username}!"
    elif score2 > 0 and score1 == 0:
        text += f"\nPoint awarded to {'Bot' if game['player2'] == 'bot' else '@' + player2_username}!"
    else:
        text += "\nNo points awarded."

    # Check for game end
    if max(game['scores'].values()) >= game['points_to_win']:
        winner = 'player1' if game['scores']['player1'] > game['scores']['player2'] else 'player2'
        winner_id = game[winner]
        prize = game['bet'] * 1.92
        if winner_id != 'bot':
            update_user_balance(winner_id, get_user_balance(winner_id) + prize + game['bet'])
        winner_username = player1_username if winner == 'player1' else player2_username

        text = (
            f"🏀 Final Round Results\n"
            f"Mode: {game['mode']}\n"
            f"@{player1_username} shots: {shots1}, score: {score1}\n"
            f"{'Bot' if game['player2'] == 'bot' else '@' + player2_username} shots: {shots2}, score: {score2}\n"
            f"🏀 Final Scoreboard\n"
            f"@{player1_username}: {game['scores']['player1']}\n"
            f"{'Bot' if game['player2'] == 'bot' else '@' + player2_username}: {game['scores']['player2']}\n\n"
            f"🏆 Game over!\n"
            f"{'Bot wins! You lost $' + str(game['bet']) + '.' if winner_id == 'bot' else '🎉 @' + winner_username + ' wins $' + str(prize) + '!'}"
        )

        # Add balance to final scoreboard
        if game['player2'] == 'bot':
            player_balance = get_user_balance(game['player1'])
            text += f"\n\nYour balance: ${player_balance:.2f}"
        else:
            player1_balance = get_user_balance(game['player1'])
            player2_balance = get_user_balance(game['player2'])
            text += f"\n\n@{player1_username} balance: ${player1_balance:.2f}\n@{player2_username} balance: ${player2_balance:.2f}"

        keyboard = [
            [InlineKeyboardButton("Play Again", callback_data="basketball_play_again"),
             InlineKeyboardButton("Double", callback_data="basketball_double")]
        ]
        await send_with_retry(context.bot, chat_id, text, reply_markup=InlineKeyboardMarkup(keyboard))

        # Store last game data and clean up
        if game['player2'] != 'bot':
            last_game_p1 = {'opponent': game['player2'], 'mode': game['mode'], 'points_to_win': game['points_to_win'], 'bet': game['bet']}
            last_game_p2 = {'opponent': game['player1'], 'mode': game['mode'], 'points_to_win': game['points_to_win'], 'bet': game['bet']}
            context.bot_data.setdefault('last_games', {}).setdefault(chat_id, {})[game['player1']] = last_game_p1
            context.bot_data['last_games'][chat_id][game['player2']] = last_game_p2
            del context.bot_data['user_games'][(chat_id, game['player2'])]
        else:
            last_game = {'opponent': 'bot', 'mode': game['mode'], 'points_to_win': game['points_to_win'], 'bet': game['bet']}
            context.bot_data.setdefault('last_games', {}).setdefault(chat_id, {})[game['player1']] = last_game
        del context.bot_data['user_games'][(chat_id, game['player1'])]
        del context.bot_data['games'][game_key]
    else:
        game['rolls'] = {'player1': [], 'player2': []}
        game['roll_count'] = {'player1': 0, 'player2': 0}
        game['current_player'] = 'player1'
        game['round_number'] += 1
        text += f"\n\nRound {game['round_number']}: @{player1_username}, your turn! Tap the button to take a shot."
        keyboard = [[InlineKeyboardButton(f"🏀 Take a Shot (Round {game['round_number']})", callback_data=f"basketball_take_shot_{game['round_number']}")]]
        await send_with_retry(context.bot, chat_id, text, reply_markup=InlineKeyboardMarkup(keyboard))

# Command handler for /basketball
async def basketball_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    args = context.args

    if not user_exists(user_id):
        await send_with_retry(context.bot, chat_id, "Please register with /start.")
        return

    if len(args) != 1:
        await send_with_retry(context.bot, chat_id, "Usage: /basketball <amount>\nExample: /basketball 1")
        return

    try:
        amount = float(args[0])
        if amount <= 0:
            raise ValueError("Bet must be positive.")
        balance = get_user_balance(user_id)
        if amount > balance:
            await send_with_retry(context.bot, chat_id, f"Insufficient balance! You have ${balance:.2f}.")
            return
        if (chat_id, user_id) in context.bot_data.get('user_games', {}):
            await send_with_retry(context.bot, chat_id, "You are already in a game!")
            return
        context.user_data['basketball_bet'] = amount
        context.user_data['basketball_initiator'] = user_id

        keyboard = [
            [InlineKeyboardButton("🏀 Normal Mode", callback_data="basketball_mode_normal")],
            [InlineKeyboardButton("🏀 Double Shot", callback_data="basketball_mode_double")],
            [InlineKeyboardButton("🏀 Crazy Mode", callback_data="basketball_mode_crazy")],
            [InlineKeyboardButton("ℹ️ Mode Guide", callback_data="basketball_mode_guide"),
             InlineKeyboardButton("❌ Cancel", callback_data="basketball_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_with_retry(context.bot, chat_id, "🏀 Choose the game mode:", reply_markup=reply_markup)

    except ValueError as e:
        await send_with_retry(context.bot, chat_id, f"Invalid bet amount: {str(e)}. Use a positive number.")

# Start game against bot
async def start_game_against_bot(context, chat_id, user_id, bet, mode, points):
    if (chat_id, user_id) in context.bot_data.get('user_games', {}):
        await send_with_retry(context.bot, chat_id, "You are already in a game!")
        return
    balance = get_user_balance(user_id)
    if bet > balance:
        await send_with_retry(context.bot, chat_id, f"Insufficient balance! You need ${bet:.2f} but have ${balance:.2f}.")
        return
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
        f"🏀 Match started!\n"
        f"Player 1: @{player1_username}\n"
        f"Player 2: Bot\n\n"
        f"Round 1: @{player1_username}, your turn! Tap the button to take a shot."
    )
    keyboard = [[InlineKeyboardButton("🏀 Take a Shot (Round 1)", callback_data="basketball_take_shot_1")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_with_retry(context.bot, chat_id, text, reply_markup=reply_markup)

# Button handler for basketball game
async def basketball_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data = query.data

    if data == "basketball_mode_guide":
        guide_text = (
            "🏀 **Normal Mode**: Take one shot, rolls of 4 or higher count as a score.\n\n"
            "🏀 **Double Shot**: Take two shots, sum of rolls that are 4 or higher counts as your score.\n\n"
            "🏀 **Crazy Mode**: Take one shot, rolling a 1 counts as a score (you win by missing).\n\n"
            "In all modes, you get a point only if your score is greater than 0 and your opponent's score is 0."
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="basketball_back")]]
        await query.edit_message_text(guide_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    elif data == "basketball_back":
        keyboard = [
            [InlineKeyboardButton("🏀 Normal Mode", callback_data="basketball_mode_normal")],
            [InlineKeyboardButton("🏀 Double Shot", callback_data="basketball_mode_double")],
            [InlineKeyboardButton("🏀 Crazy Mode", callback_data="basketball_mode_crazy")],
            [InlineKeyboardButton("ℹ️ Mode Guide", callback_data="basketball_mode_guide"),
             InlineKeyboardButton("❌ Cancel", callback_data="basketball_cancel")]
        ]
        await query.edit_message_text("🏀 Choose the game mode:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif data == "basketball_cancel":
        if 'basketball_initiator' in context.user_data and context.user_data['basketball_initiator'] == user_id:
            context.user_data.clear()
            await query.edit_message_text("❌ Game setup cancelled.")
        return

    elif data.startswith("basketball_mode_"):
        if 'basketball_initiator' not in context.user_data or context.user_data['basketball_initiator'] != user_id:
            return
        mode = data.split('_')[2]
        context.user_data['basketball_mode'] = mode
        keyboard = [
            [InlineKeyboardButton("🏆 First to 1 point", callback_data="basketball_points_1")],
            [InlineKeyboardButton("🏅 First to 2 points", callback_data="basketball_points_2")],
            [InlineKeyboardButton("🥇 First to 3 points", callback_data="basketball_points_3")],
            [InlineKeyboardButton("❌ Cancel", callback_data="basketball_cancel")]
        ]
        await query.edit_message_text("🏀 Choose points to win:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("basketball_points_"):
        if 'basketball_initiator' not in context.user_data or context.user_data['basketball_initiator'] != user_id:
            return
        points = int(data.split('_')[2])
        context.user_data['basketball_points'] = points
        bet = context.user_data['basketball_bet']
        mode = context.user_data['basketball_mode'].capitalize()
        text = (
            f"🏀 **Game confirmation**\n"
            f"Game: Basketball 🏀\n"
            f"First to {points} points\n"
            f"Mode: {mode} Mode\n"
            f"Your bet: ${bet:.2f}\n"
            f"Win multiplier: 1.92x"
        )
        keyboard = [
            [InlineKeyboardButton("✅ Confirm", callback_data="basketball_confirm_setup"),
             InlineKeyboardButton("❌ Cancel", callback_data="basketball_cancel")]
        ]
        await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "basketball_confirm_setup":
        if 'basketball_initiator' not in context.user_data or context.user_data['basketball_initiator'] != user_id:
            return
        bet = context.user_data['basketball_bet']
        mode = context.user_data['basketball_mode'].capitalize()
        points = context.user_data['basketball_points']
        username = (await context.bot.get_chat_member(chat_id, user_id)).user.username or "Someone"
        mode_description = {
            "normal": "Take one shot, rolls of 4 or higher count as a score.",
            "double": "Take two shots, sum of rolls that are 4 or higher counts as your score.",
            "crazy": "Take one shot, rolling a 1 counts as a score (you win by missing)."
        }
        text = (
            f"🏀 {username} wants to play Basketball!\n\n"
            f"Bet: ${bet:.2f}\n"
            f"Win multiplier: 1.92x\n"
            f"Mode: First to {points} points\n\n"
            f"{mode} Mode: {mode_description[context.user_data['basketball_mode']]}"
        )
        keyboard = [
            [InlineKeyboardButton("🤝 Challenge a Player", callback_data="basketball_challenge")],
            [InlineKeyboardButton("🤖 Play against Bot", callback_data="basketball_bot")]
        ]
        await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "basketball_challenge":
        if 'basketball_initiator' not in context.user_data or context.user_data['basketball_initiator'] != user_id:
            return
        context.user_data['expecting_username'] = True
        await send_with_retry(context.bot, chat_id, "Enter the username of the player you want to challenge (e.g., @username):")

    elif data == "basketball_bot":
        bet = context.user_data['basketball_bet']
        mode = context.user_data['basketball_mode']
        points = context.user_data['basketball_points']
        await start_game_against_bot(context, chat_id, user_id, bet, mode, points)

    elif data.startswith("basketball_accept_"):
        game_id = int(data.split('_')[2])
        if game_id not in context.bot_data.get('pending_challenges', {}):
            await query.edit_message_text("❌ Challenge no longer valid.")
            return
        game = context.bot_data['pending_challenges'][game_id]
        if user_id != game['challenged']:
            return
        if (chat_id, game['initiator']) in context.bot_data.get('user_games', {}) or (chat_id, user_id) in context.bot_data.get('user_games', {}):
            await send_with_retry(context.bot, chat_id, "One of you is already in a game!")
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
            f"🏀 Match started!\n"
            f"Player 1: @{player1_username}\n"
            f"Player 2: @{player2_username}\n\n"
            f"Round 1: @{player1_username}, your turn! Tap the button to take a shot."
        )
        keyboard = [[InlineKeyboardButton("🏀 Take a Shot (Round 1)", callback_data="basketball_take_shot_1")]]
        await send_with_retry(context.bot, chat_id, text, reply_markup=InlineKeyboardMarkup(keyboard))
        del context.bot_data['pending_challenges'][game_id]

    elif data.startswith("basketball_cancel_"):
        game_id = int(data.split('_')[2])
        if game_id not in context.bot_data.get('pending_challenges', {}):
            await query.edit_message_text("❌ Challenge no longer valid.")
            return
        game = context.bot_data['pending_challenges'][game_id]
        initiator_username = (await context.bot.get_chat_member(chat_id, game['initiator'])).user.username or "Someone"
        text = f"❌ {initiator_username}'s challenge was declined."
        await query.edit_message_text(text=text)
        del context.bot_data['pending_challenges'][game_id]

    elif data.startswith("basketball_take_shot_"):
        game_key = context.bot_data.get('user_games', {}).get((chat_id, user_id))
        if not game_key:
            await send_with_retry(context.bot, chat_id, "No active game found!")
            return
        game = context.bot_data.get('games', {}).get(game_key)
        if not game:
            await send_with_retry(context.bot, chat_id, "Game data missing!")
            return
        if max(game['scores'].values()) >= game['points_to_win']:
            await send_with_retry(context.bot, chat_id, "The game has already ended!")
            return
        player_key = 'player1' if game['player1'] == user_id else 'player2' if game['player2'] == user_id else None
        if not player_key:
            return
        turn_round = int(data.split('_')[3])
        if turn_round != game['round_number']:
            await send_with_retry(context.bot, chat_id, "This button is from a previous round!")
            return
        if player_key != game['current_player']:
            await send_with_retry(context.bot, chat_id, "It's not your turn!")
            return
        
        shot_msg = await context.bot.send_dice(chat_id=chat_id, emoji='🏀')
        await asyncio.sleep(4)  # Wait for dice animation
        shot_value = shot_msg.dice.value
        game['rolls'][player_key].append(shot_value)
        game['roll_count'][player_key] += 1
        await asyncio.sleep(1)  # Delay for thrill

        if game['roll_count'][player_key] < game['rolls_needed']:
            keyboard = [[InlineKeyboardButton(f"🏀 Take Another Shot (Round {game['round_number']})", callback_data=f"basketball_take_shot_{game['round_number']}")]]
            await send_with_retry(context.bot, chat_id, f"Round {game['round_number']}: Take another shot!", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            other_player = 'player2' if player_key == 'player1' else 'player1'
            game['current_player'] = other_player
            if game[other_player] == 'bot':
                bot_shots = []
                for _ in range(game['rolls_needed'] - game['roll_count'][other_player]):
                    shot_msg = await context.bot.send_dice(chat_id=chat_id, emoji='🏀')
                    await asyncio.sleep(4)
                    bot_shots.append(shot_msg.dice.value)
                game['rolls'][other_player].extend(bot_shots)
                game['roll_count'][other_player] += len(bot_shots)
                await asyncio.sleep(1)  # Delay after bot shot

            if game['roll_count']['player1'] == game['rolls_needed'] and game['roll_count']['player2'] == game['rolls_needed']:
                await asyncio.sleep(2)  # Suspense before result
                await evaluate_round(game, chat_id, game_key, context)
            else:
                other_username = (await context.bot.get_chat_member(chat_id, game[other_player])).user.username or "Player"
                keyboard = [[InlineKeyboardButton(f"🏀 Take a Shot (Round {game['round_number']})", callback_data=f"basketball_take_shot_{game['round_number']}")]]
                await send_with_retry(context.bot, chat_id, f"Round {game['round_number']}: @{other_username}, your turn!", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "basketball_play_again":
        last_games = context.bot_data.get('last_games', {}).get(chat_id, {})
        last_game = last_games.get(user_id)
        if not last_game:
            await send_with_retry(context.bot, chat_id, "No previous game found.")
            return
        opponent = last_game['opponent']
        mode = last_game['mode']
        points = last_game['points_to_win']
        bet = last_game['bet']
        if opponent == 'bot':
            await start_game_against_bot(context, chat_id, user_id, bet, mode, points)
        else:
            await send_with_retry(context.bot, chat_id, "Play Again is only supported against the bot currently.")

    elif data == "basketball_double":
        last_games = context.bot_data.get('last_games', {}).get(chat_id, {})
        last_game = last_games.get(user_id)
        if not last_game:
            await send_with_retry(context.bot, chat_id, "No previous game found.")
            return
        opponent = last_game['opponent']
        mode = last_game['mode']
        points = last_game['points_to_win']
        bet = last_game['bet'] * 2
        if opponent == 'bot':
            await start_game_against_bot(context, chat_id, user_id, bet, mode, points)
        else:
            await send_with_retry(context.bot, chat_id, "Double is only supported against the bot currently.")

# Text handler for username input in basketball game
async def basketball_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if context.user_data.get('expecting_username') and context.user_data.get('basketball_initiator') == user_id:
        username = update.message.text.strip()
        if not username.startswith('@'):
            await send_with_retry(context.bot, chat_id, "Invalid username. Use @username.")
            return
        username = username[1:]
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            c.execute("SELECT user_id FROM users WHERE username = ?", (username,))
            result = c.fetchone()
        if not result:
            await send_with_retry(context.bot, chat_id, f"User @{username} not found.")
            return
        challenged_user_id = result[0]
        if challenged_user_id == user_id:
            await send_with_retry(context.bot, chat_id, "You can't challenge yourself!")
            return
        if get_user_balance(challenged_user_id) < context.user_data['basketball_bet']:
            await send_with_retry(context.bot, chat_id, f"@{username} doesn’t have enough balance!")
            return
        if (chat_id, challenged_user_id) in context.bot_data.get('user_games', {}):
            await send_with_retry(context.bot, chat_id, f"@{username} is already in a game!")
            return
        game_id = len(context.bot_data.get('pending_challenges', {})) + 1
        context.bot_data.setdefault('pending_challenges', {})[game_id] = {
            'initiator': user_id,
            'challenged': challenged_user_id,
            'mode': context.user_data['basketball_mode'],
            'points_to_win': context.user_data['basketball_points'],
            'bet': context.user_data['basketball_bet']
        }
        initiator_username = (await context.bot.get_chat_member(chat_id, user_id)).user.username or "Someone"
        text = (
            f"🏀 {initiator_username} challenges {username}!\n"
            f"Bet: ${context.user_data['basketball_bet']:.2f}\n"
            f"Mode: {context.user_data['basketball_mode'].capitalize()}\n"
            f"First to {context.user_data['basketball_points']} points"
        )
        keyboard = [
            [InlineKeyboardButton("Accept", callback_data=f"basketball_accept_{game_id}"),
             InlineKeyboardButton("Cancel", callback_data=f"basketball_cancel_{game_id}")]
        ]
        await send_with_retry(context.bot, chat_id, text, reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data['expecting_username'] = False