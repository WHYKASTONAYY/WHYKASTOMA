import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database import user_exists, get_user_balance, update_user_balance
from utils import logger

def get_combo_parts(dice_value: int) -> list[str]:
    """Convert dice value to a list of slot symbols."""
    values = ["🍫", "🍇", "🍋", "7️⃣"]
    dice_value -= 1
    result = []
    for _ in range(3):
        result.append(values[dice_value % 4])
        dice_value //= 4
    return result

def get_payout(symbols: list[str]) -> float:
    """Calculate payout multiplier based on slot symbols."""
    s1, s2, s3 = symbols
    if s1 == '7️⃣' and s2 == '7️⃣' and s3 == '7️⃣':
        return 20.0
    elif s1 == s2 == s3:
        if s1 == '🍫':
            return 7.0
        elif s1 == '🍋':
            return 7.0
        elif s1 == '🍇':
            return 7.0
    elif s1 == '7️⃣' and s2 == '7️⃣':
        return 2.0
    elif s2 == '7️⃣' and s3 == '7️⃣':
        return 1.0
    elif s1 == s2:
        if s1 == '🍫':
            return 0.5
        elif s1 == '🍋':
            return 0.25
        elif s1 == '🍇':
            return 0.25
    return 0.0

async def slots_command(update, context):
    """Handle the /slots command to start a new game."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Restrict slots to private chats (unchanged behavior)
    if update.message.chat.type != 'private':
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Slots are only available in my private chat. Click here to play: https://t.me/{context.bot.username}"
        )
        return

    # Check if user is registered
    if not user_exists(user_id):
        await context.bot.send_message(chat_id=chat_id, text="Please register with /start.")
        return

    # Prevent multiple active games
    if 'slots_game' in context.user_data:
        await context.bot.send_message(chat_id=chat_id, text="You already have an active slots game. Finish or cancel it first.")
        return

    # Initialize game state
    balance = get_user_balance(user_id)
    bet_size = 1.0
    text = f"💰 Balance: ${balance:.2f}\n\nChoose the bet size:"
    keyboard = [
        [InlineKeyboardButton("-1", callback_data="slots_bet_-1"),
         InlineKeyboardButton(f"${bet_size:.2f}", callback_data="slots_noop"),
         InlineKeyboardButton("+1", callback_data="slots_bet_+1")],
        [InlineKeyboardButton("Min", callback_data="slots_bet_min"),
         InlineKeyboardButton("Double", callback_data="slots_bet_double"),
         InlineKeyboardButton("Max", callback_data="slots_bet_max")],
        [InlineKeyboardButton("Combos", callback_data="slots_show_combos"),
         InlineKeyboardButton("🎰 Spin", callback_data="slots_spin"),
         InlineKeyboardButton("❌ Cancel", callback_data="slots_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    context.user_data['slots_game'] = {'bet_size': bet_size, 'message_id': message.message_id}

async def slots_button_handler(update, context):
    """Handle button interactions for the slots game."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    game = context.user_data.get('slots_game')

    # Validate game state and message ID
    if not game or 'message_id' not in game or query.message.message_id != game['message_id']:
        await query.answer("This game has ended or the button is outdated.")
        return

    balance = get_user_balance(user_id)
    bet_size = game['bet_size']

    if data == "slots_cancel":
        # Cancel the game and clean up
        del context.user_data['slots_game']
        await context.bot.delete_message(chat_id=chat_id, message_id=game['message_id'])
        await context.bot.send_message(chat_id=chat_id, text="Slots game cancelled.")
        return

    elif data == "slots_spin":
        # Handle spinning the slots
        if balance < bet_size:
            await query.answer("Not enough balance to spin!", show_alert=True)
            return

        await context.bot.delete_message(chat_id=chat_id, message_id=game['message_id'])
        dice_message = await context.bot.send_dice(chat_id=chat_id, emoji='🎰')
        dice_value = dice_message.dice.value
        symbols = get_combo_parts(dice_value)
        payout_multiplier = get_payout(symbols)

        if payout_multiplier > 0:
            winnings = bet_size * payout_multiplier
            balance += winnings
            update_user_balance(user_id, balance)
            outcome_text = f"{symbols[0]} {symbols[1]} {symbols[2]}\n\nYou won ${winnings:.2f}!"
        else:
            balance -= bet_size
            update_user_balance(user_id, balance)
            outcome_text = f"{symbols[0]} {symbols[1]} {symbols[2]}\n\nNo win this time."

        await asyncio.sleep(3)
        text = f"💰 Balance: ${balance:.2f}\n\n{outcome_text}\n\nChoose the bet size:"
        keyboard = [
            [InlineKeyboardButton("-1", callback_data="slots_bet_-1"),
             InlineKeyboardButton(f"${bet_size:.2f}", callback_data="slots_noop"),
             InlineKeyboardButton("+1", callback_data="slots_bet_+1")],
            [InlineKeyboardButton("Min", callback_data="slots_bet_min"),
             InlineKeyboardButton("Double", callback_data="slots_bet_double"),
             InlineKeyboardButton("Max", callback_data="slots_bet_max")],
            [InlineKeyboardButton("Combos", callback_data="slots_show_combos"),
             InlineKeyboardButton("🎰 Spin", callback_data="slots_spin"),
             InlineKeyboardButton("❌ Cancel", callback_data="slots_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        game['message_id'] = message.message_id

    elif data.startswith("slots_bet_"):
        # Adjust bet size
        if data == "slots_bet_-1":
            bet_size = max(0.25, bet_size - 1)
        elif data == "slots_bet_+1":
            bet_size = min(50, bet_size + 1)
        elif data == "slots_bet_min":
            bet_size = 0.25
        elif data == "slots_bet_double":
            bet_size = min(50, bet_size * 2)
        elif data == "slots_bet_max":
            bet_size = 50
        game['bet_size'] = bet_size
        text = f"💰 Balance: ${balance:.2f}\n\nChoose the bet size:"
        keyboard = [
            [InlineKeyboardButton("-1", callback_data="slots_bet_-1"),
             InlineKeyboardButton(f"${bet_size:.2f}", callback_data="slots_noop"),
             InlineKeyboardButton("+1", callback_data="slots_bet_+1")],
            [InlineKeyboardButton("Min", callback_data="slots_bet_min"),
             InlineKeyboardButton("Double", callback_data="slots_bet_double"),
             InlineKeyboardButton("Max", callback_data="slots_bet_max")],
            [InlineKeyboardButton("Combos", callback_data="slots_show_combos"),
             InlineKeyboardButton("🎰 Spin", callback_data="slots_spin"),
             InlineKeyboardButton("❌ Cancel", callback_data="slots_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=game['message_id'],
            reply_markup=reply_markup
        )

    elif data == "slots_show_combos":
        # Display winning combinations
        combos_text = (
            "Winning combinations:\n\n"
            "7️⃣7️⃣7️⃣ — 20x Jackpot!\n"
            "🍫🍫🍫 — 7x\n"
            "🍋🍋🍋 — 7x\n"
            "🍇🍇🍇 — 7x\n"
            "7️⃣7️⃣❔ — 2x\n"
            "❔7️⃣7️⃣ — 1x\n"
            "🍫🍫❔ — 0.5x\n"
            "🍋🍋❔ — 0.25x\n"
            "🍇🍇❔ — 0.25x\n\n"
            "❔ represents any symbol\n"
            "🍀 Good Luck!"
        )
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="slots_back")]]
        await context.bot.edit_message_text(
            combos_text,
            chat_id=chat_id,
            message_id=game['message_id'],
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "slots_back":
        # Return to main betting interface
        text = f"💰 Balance: ${balance:.2f}\n\nChoose the bet size:"
        keyboard = [
            [InlineKeyboardButton("-1", callback_data="slots_bet_-1"),
             InlineKeyboardButton(f"${bet_size:.2f}", callback_data="slots_noop"),
             InlineKeyboardButton("+1", callback_data="slots_bet_+1")],
            [InlineKeyboardButton("Min", callback_data="slots_bet_min"),
             InlineKeyboardButton("Double", callback_data="slots_bet_double"),
             InlineKeyboardButton("Max", callback_data="slots_bet_max")],
            [InlineKeyboardButton("Combos", callback_data="slots_show_combos"),
             InlineKeyboardButton("🎰 Spin", callback_data="slots_spin"),
             InlineKeyboardButton("❌ Cancel", callback_data="slots_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=game['message_id'],
            reply_markup=reply_markup
        )
