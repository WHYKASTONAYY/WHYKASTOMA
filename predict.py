# predict/predict.py
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database import get_user_balance, update_user_balance
from utils import logger

MODE_ORDER = ["dice", "dart", "bowling", "football", "basketball"]

MODES = {
    "dice": {"emoji": "🎲"},
    "dart": {"emoji": "🎯"},
    "bowling": {"emoji": "🎳"},
    "football": {"emoji": "⚽"},
    "basketball": {"emoji": "🏀"}
}

MULTIPLIERS = {
    "dice": 5.76,
    "dart": 5.76,
    "bowling": 5.76,
    "football": {
        "goal": 1.6,
        "miss": 2.4,
        "bar": 2.4
    },
    "basketball": {
        "score": 2.3,
        "miss": 1.6,
        "stuck": 3.7
    }
}

def get_multiplier(mode, prediction):
    multipliers = MULTIPLIERS[mode]
    if isinstance(multipliers, dict):
        return multipliers.get(prediction, 0)
    return multipliers

async def predict_command(update, context):
    user_id = update.effective_user.id
    if "predict_game" not in context.user_data:
        context.user_data["predict_game"] = {
            "mode": "dice",
            "prediction": None,
            "last_prediction": None,
            "last_outcome": None,
            "bet": 1.0,
            "message_id": None
        }
    await send_prompt(update, context)

async def send_prompt(update, context, result_text=None):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    game = context.user_data["predict_game"]
    mode = game["mode"]
    prediction = game["prediction"]
    bet = game["bet"]
    balance = get_user_balance(user_id)

    if prediction:
        multiplier = get_multiplier(mode, prediction)
        prediction_text = f"Your prediction: {prediction}\nMultiplier: {multiplier:.2f}x"
    else:
        prediction_text = "Make your prediction:"

    if result_text:
        text = f"{MODES[mode]['emoji']} {mode.capitalize()} Prediction\n\nLast game result:\n{result_text}\n\nYour balance: ${balance:.2f}\n\n{prediction_text}"
    else:
        text = f"{MODES[mode]['emoji']} {mode.capitalize()} Prediction\n\nYour balance: ${balance:.2f}\n\n{prediction_text}"

    if mode in ["dice", "dart", "bowling"]:
        prediction_buttons = [
            InlineKeyboardButton(f"{i} ✅" if prediction == str(i) else str(i), callback_data=f"predict_{i}")
            for i in range(1, 7)
        ]
    elif mode == "football":
        options = ["goal", "miss", "bar"]
        prediction_buttons = [
            InlineKeyboardButton(f"{opt} ✅" if prediction == opt else opt, callback_data=f"predict_{opt}")
            for opt in options
        ]
    elif mode == "basketball":
        options = ["score", "miss", "stuck"]
        prediction_buttons = [
            InlineKeyboardButton(f"{opt} ✅" if prediction == opt else opt, callback_data=f"predict_{opt}")
            for opt in options
        ]
    prediction_buttons = [prediction_buttons]

    half_bet = max(0.25, bet / 2)
    double_bet = min(50.0, bet * 2)
    bet_buttons = [
        InlineKeyboardButton("Half Bet", callback_data="predict_bet_half"),
        InlineKeyboardButton(f"Bet ${bet:.2f}", callback_data="noop"),
        InlineKeyboardButton("Double Bet", callback_data="predict_bet_double")
    ]

    mode_index = MODE_ORDER.index(mode)
    mode_buttons = [
        InlineKeyboardButton("⬅️", callback_data="predict_mode_left"),
        InlineKeyboardButton(MODES[mode]["emoji"], callback_data="noop"),
        InlineKeyboardButton("➡️", callback_data="predict_mode_right")
    ]

    start_cancel_buttons = [
        InlineKeyboardButton("❌ Cancel", callback_data="predict_cancel"),
        InlineKeyboardButton("▶️ Start", callback_data="predict_start")
    ]

    keyboard = [prediction_buttons[0], bet_buttons, mode_buttons, start_cancel_buttons]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if "message_id" in game and game["message_id"]:
        try:
            await context.bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=game["message_id"],
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Failed to edit message: {e}")
            message = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
            game["message_id"] = message.message_id
    else:
        message = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        game["message_id"] = message.message_id

async def predict_button_handler(update, context):
    query = update.callback_query
    data = query.data
    if not data.startswith("predict_"):
        return
    action = data[len("predict_"):]
    game = context.user_data.get("predict_game")
    if not game:
        return
    user_id = query.from_user.id
    mode = game["mode"]

    if action == "bet_half":
        game["bet"] = max(0.25, game["bet"] / 2)
        await send_prompt(update, context)
    elif action == "bet_double":
        game["bet"] = min(50.0, game["bet"] * 2)
        await send_prompt(update, context)
    elif action == "mode_left":
        mode_index = MODE_ORDER.index(mode)
        game["mode"] = MODE_ORDER[(mode_index - 1) % len(MODE_ORDER)]
        game["prediction"] = None
        await send_prompt(update, context)
    elif action == "mode_right":
        mode_index = MODE_ORDER.index(mode)
        game["mode"] = MODE_ORDER[(mode_index + 1) % len(MODE_ORDER)]
        game["prediction"] = None
        await send_prompt(update, context)
    elif action == "start":
        if game["prediction"] is None:
            await query.answer("Please make a prediction first!", show_alert=True)
            return
        bet = game["bet"]
        balance = get_user_balance(user_id)
        if balance < bet:
            await query.answer("Insufficient balance!", show_alert=True)
            return
        balance -= bet
        update_user_balance(user_id, balance)
        emoji = MODES[mode]["emoji"]
        dice_message = await context.bot.send_dice(chat_id=query.message.chat_id, emoji=emoji)
        dice_value = int(dice_message.dice.value)
        if mode in ["dice", "dart", "bowling"]:
            outcome = str(dice_value)
        elif mode == "football":
            outcome = "goal" if dice_value in [4, 5] else "bar" if dice_value == 3 else "miss"
        elif mode == "basketball":
            outcome = "score" if dice_value in [4, 5] else "stuck" if dice_value == 3 else "miss"
        prediction = game["prediction"]
        if prediction == outcome:
            multiplier = get_multiplier(mode, prediction)
            winnings = bet * multiplier
            balance += winnings
            update_user_balance(user_id, balance)
            result_text = f"✅ Won: Predicted '{prediction}', got '{outcome}' - +${winnings:.2f}"
        else:
            result_text = f"❌ Lost: Predicted '{prediction}', got '{outcome}'"
        game["last_prediction"] = prediction
        game["last_outcome"] = outcome
        game["prediction"] = None
        await asyncio.sleep(3)
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=game["message_id"])
        except Exception as e:
            logger.error(f"Failed to delete message: {e}")
        await send_prompt(update, context, result_text=result_text)
    elif action == "cancel":
        del context.user_data["predict_game"]
        await context.bot.delete_message(chat_id=query.message.chat_id, message_id=game["message_id"])
        await context.bot.send_message(chat_id=query.message.chat_id, text="Game cancelled.")
    else:
        game["prediction"] = action
        await send_prompt(update, context)