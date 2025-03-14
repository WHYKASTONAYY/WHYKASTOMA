import asyncio
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from database import user_exists, get_user_balance, update_user_balance
from utils import logger, send_with_retry

# Probability that the player wins (40% player win rate, 60% bot win rate)
PLAYER_WIN_PROB = 0.4

# Sticker IDs for heads and tails
STICKER_IDS = {
    'heads': "CAACAgQAAxkBAAEN6HdnwG1452Y9MGXHJAK_6gYZ5LiccQACnRUAAjGMAVKanS00zj4iTjYE",
    'tails': "CAACAgQAAxkBAAEN6HVnwG1uwwdFCy4enrq4YB3yZPjfJQAC8hQAAhGdAVKUEJvAA6dPaDYE"
}

async def coin_command(update, context):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    args = context.args

    try:
        if len(args) != 1:
            raise ValueError("Usage: /coin <amount>\nExample: /coin 1")
        amount = float(args[0])
        if amount <= 0:
            raise ValueError("Bet must be positive.")
        if not user_exists(user_id):
            raise ValueError("Please register with /start.")
        balance = get_user_balance(user_id)
        if amount > balance:
            raise ValueError(f"Insufficient balance! You have ${balance:.2f}.")
        context.user_data['coin_bet'] = amount
        context.user_data['coin_initiator'] = user_id

        keyboard = [
            [InlineKeyboardButton("Heads (Trump)", callback_data="coin_heads")],
            [InlineKeyboardButton("Tails (Dice Logo)", callback_data="coin_tails")],
            [InlineKeyboardButton("❌ Cancel", callback_data="coin_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_with_retry(context.bot, chat_id, "🪙 Choose the coin side:", reply_markup=reply_markup)

    except ValueError as e:
        await send_with_retry(context.bot, chat_id, str(e))

async def coin_button_handler(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data = query.data

    if data == "coin_cancel":
        if 'coin_initiator' in context.user_data and context.user_data['coin_initiator'] == user_id:
            del context.user_data['coin_initiator']
            await query.edit_message_text("❌ Game setup cancelled.")
        return

    elif data in ["coin_heads", "coin_tails"]:
        if 'coin_initiator' not in context.user_data or context.user_data['coin_initiator'] != user_id:
            return
        context.user_data['coin_choice'] = "heads" if data == "coin_heads" else "tails"
        bet = context.user_data['coin_bet']
        text = (
            "🪙 **Game confirmation**\n\n"
            "Game: Coinflip 🪙\n"
            "First to 1 point\n"
            "Mode: Normal Mode\n"
            f"Your bet: ${bet:.2f}\n"
            "Win multiplier: 1.92x"
        )
        keyboard = [
            [InlineKeyboardButton("✅ Confirm", callback_data="coin_confirm"),
             InlineKeyboardButton("❌ Cancel", callback_data="coin_cancel")]
        ]
        await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "coin_confirm":
        if 'coin_initiator' not in context.user_data or context.user_data['coin_initiator'] != user_id:
            return
        bet = context.user_data['coin_bet']
        username = query.from_user.username or "Someone"
        text = (
            f"🪙 {username} wants to play Coinflip!\n\n"
            f"Bet: ${bet:.2f}\n"
            "Win multiplier: 1.92x\n"
            "Mode: First to 1 point\n\n"
            "Normal Mode\n"
            "Basic game mode. Choose heads or tails, and see if you win the flip."
        )
        keyboard = [
            [InlineKeyboardButton("Play vs Bot", callback_data="coin_bot")]
        ]
        await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "coin_bot":
        if 'coin_initiator' not in context.user_data or context.user_data['coin_initiator'] != user_id:
            return
        bet = context.user_data['coin_bet']
        choice = context.user_data['coin_choice']
        username = query.from_user.username or "Player"
        text = (
            "🪙 Match accepted!\n\n"
            f"Player 1: {username}\n"
            "Player 2: Bot\n\n"
            f"{username}, your turn! To start, click the button below"
        )
        keyboard = [[InlineKeyboardButton("Flip the Coin", callback_data="coin_flip")]]
        match_message = await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard))
        context.bot_data.setdefault('coin_games', {})[(chat_id, user_id)] = {
            'bet': bet,
            'choice': choice,
            'match_message_id': match_message.message_id
        }

    elif data == "coin_flip":
        game = context.bot_data['coin_games'].get((chat_id, user_id))
        if not game:
            return
        await asyncio.sleep(2)  # Simulate flip delay

        player_choice = game['choice']
        if random.random() < PLAYER_WIN_PROB:
            coin_result = player_choice  # Player wins (40% chance)
        else:
            coin_result = 'tails' if player_choice == 'heads' else 'heads'  # Bot wins (60% chance)

        sticker_id = STICKER_IDS[coin_result]
        try:
            await context.bot.send_sticker(
                chat_id=chat_id,
                sticker=sticker_id,
                reply_to_message_id=game['match_message_id']
            )
            await asyncio.sleep(3)  # Delay after sticker
        except Exception as e:
            logger.error(f"Failed to send sticker: {e}")

        username = query.from_user.username or "Player"
        if game['choice'] == coin_result:
            winnings = game['bet'] * 1.92
            new_balance = get_user_balance(user_id) + winnings - game['bet']
            update_user_balance(user_id, new_balance)
            outcome_text = (
                f"🏆 Game over! The coin landed on {coin_result}.\n\n"
                f"Score:\n{username} • 1\nBot • 0\n\n"
                f"🎉 Congratulations, {username}! You won ${winnings:.2f}!\n"
                f"New balance: ${new_balance:.2f}"
            )
        else:
            new_balance = get_user_balance(user_id) - game['bet']
            update_user_balance(user_id, new_balance)
            outcome_text = (
                f"🏆 Game over! The coin landed on {coin_result}.\n\n"
                f"Score:\n{username} • 0\nBot • 1\n\n"
                f"Bot wins! You lost ${game['bet']:.2f}.\n"
                f"New balance: ${new_balance:.2f}"
            )

        keyboard = [
            [InlineKeyboardButton("Play Again", callback_data="coin_restart"),
             InlineKeyboardButton("Double", callback_data="coin_double")]
        ]
        await send_with_retry(
            context.bot,
            chat_id,
            outcome_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            reply_to_message_id=game['match_message_id']
        )

        if 'coin_initiator' in context.user_data:
            del context.user_data['coin_initiator']
        del context.bot_data['coin_games'][(chat_id, user_id)]

    elif data == "coin_restart":
        if 'coin_bet' in context.user_data:
            bet = context.user_data['coin_bet']
            balance = get_user_balance(user_id)
            if bet > balance:
                await send_with_retry(context.bot, chat_id, f"Insufficient balance! You have ${balance:.2f}.")
                return
            context.user_data['coin_initiator'] = user_id
            keyboard = [
                [InlineKeyboardButton("Heads (Trump)", callback_data="coin_heads")],
                [InlineKeyboardButton("Tails (Dice Logo)", callback_data="coin_tails")],
                [InlineKeyboardButton("❌ Cancel", callback_data="coin_cancel")]
            ]
            await send_with_retry(context.bot, chat_id, f"🪙 Starting a new game with ${bet:.2f}. Choose the coin side:", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await send_with_retry(context.bot, chat_id, "No previous game found. Use /coin <amount> to start a new game.")

    elif data == "coin_double":
        if 'coin_bet' in context.user_data:
            bet = context.user_data['coin_bet'] * 2
            balance = get_user_balance(user_id)
            if bet > balance:
                await send_with_retry(context.bot, chat_id, f"Insufficient balance to double your bet! You have ${balance:.2f}.")
                return
            context.user_data['coin_bet'] = bet
            context.user_data['coin_initiator'] = user_id
            keyboard = [
                [InlineKeyboardButton("Heads (Trump)", callback_data="coin_heads")],
                [InlineKeyboardButton("Tails (Dice Logo)", callback_data="coin_tails")],
                [InlineKeyboardButton("❌ Cancel", callback_data="coin_cancel")]
            ]
            await send_with_retry(context.bot, chat_id, f"🪙 Doubling your bet to ${bet:.2f}. Choose the coin side:", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await send_with_retry(context.bot, chat_id, "No previous bet found. Use /coin <amount> to start a new game.")