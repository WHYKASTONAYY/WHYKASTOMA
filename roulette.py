import asyncio
import random
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database import get_user_balance, update_user_balance
from utils import logger

stickers = {
    0: "CAACAgEAAxkBAAEN-Yxnx5tUg_RkiIxq2efYzEREhQamCwACfQQAAsMbOUbFEPpAy1p-TjYE",
    1: "CAACAgEAAxkBAAEN-Shnx5j-BlEJtBGesakAAS9UqglDsI0AAr8FAAKR_jhGEpRICIg9EyU2BA",
    2: "CAACAgEAAxkBAAEN-Spnx5lZbQABWN903lAnOJRV3bq1_pEAAnMFAALqyDhGMwj-M_iPOhs2BA",
    3: "CAACAgEAAxkBAAEN-Sxnx5lppzQStXmkxZCw1uQaobV2TwACygUAAnW4OEZQ3ctTpLSOTzYE",
    4: "CAACAgEAAxkBAAEN-S5nx5lzFWYr5FHbKYNsWLcvGyI16QACQgQAAv23OUaIahXiN9uF0DYE",
    5: "CAACAgEAAxkBAAEN-TBnx5mKIbJSunmjjZVs_UuZICTubAAC6gUAAjP9OUYn-jHPI5EYIDYE",
    6: "CAACAgEAAxkBAAEN-TJnx5mXG4bDBnq8jguIWujZIZQaowACdgQAAjyHOUYUn9WMDmk0ozYE",
    7: "CAACAgEAAxkBAAEN-TZnx5mo_PnN_k8I4LZD_9ZUgGSCQQAC9AQAAmbOOEZiUdex1l-iSzYE",
    8: "CAACAgEAAxkBAAEN-Tpnx5m2ruBuOgNfJFJr9oCWZdtfJQAChAQAAgyiOEYqR2xdJlEXqjYE",
    9: "CAACAgEAAxkBAAEN-T5nx5nFSzxkTKC8g6w-XNMkJvGWkAACswUAAg7LOEbQVWmrlfsk-DYE",
    10: "CAACAgEAAxkBAAEN-UJnx5nVAz0qP13PvW_CKRTT4PBZLQACCQQAArQuOEa5hRAu6RXXezYE",
    11: "CAACAgEAAxkBAAEN-URnx5nhOnnvHLKwNxfKCsZzy8wxuAACLgYAAil9OEbCK7cmUsk6AzYE",
    12: "CAACAgEAAxkBAAEN-UZnx5nsrU9s2IwJ67SLH8tt8wj7JQAC_QUAAr5jOEZ1L3-2bXB6SjYE",
    13: "CAACAgEAAxkBAAEN-Uhnx5n6Z2kKShsXmPBJKnW8-CHjUgAC_AQAAqkAAThGCbd-aOkUl2U2BA",
    14: "CAACAgEAAxkBAAEN-Upnx5oHOF7ldCtgmOsL6EfK_eoZWQACOwUAAnXFOUYDI-rEcITnQTYE",
    15: "CAACAgEAAxkBAAEN-Uxnx5oTNOtJ3Gm5wo9rgRZcWihcYAACIgUAAvGJOEZnIhgcuR1sjDYE",
    16: "CAACAgEAAxkBAAEN-VBnx5omUXjwEIY8G04EsUlDZnNvPAACdAYAArfgOEYFVFMnhMwZjjYE",
    17: "CAACAgEAAxkBAAEN-VJnx5oxsXCZqlo8rDCuXQ5MAQYBfAACMgUAAqb5OUbiZks6uWcJAzYE",
    18: "CAACAgEAAxkBAAEN-VZnx5o_U72bIttTQNZWoLWExnso2gACzQQAAnzNOUZMbsBIjOzQJjYE",
    19: "CAACAgEAAxkBAAEN-Vhnx5pLX7GuBlLLMiKZ_inWXzH0hgACzQQAAixGOEanyqMkssih0jYE",
    20: "CAACAgEAAxkBAAEN-Vxnx5pdam20pbjJth9Iy-6V9q0vPwACtQQAAjM1OEY9w87j66QmGTYE",
    21: "CAACAgEAAxkBAAEN-WBnx5ptmCpUCPkUJ_EgG91BGc-PQQAC-QUAAuDUOUbJerwikgowAAE2BA",
    22: "CAACAgEAAxkBAAEN-V5nx5przwZ8la7UMix8LfTv0UlNRQACiwMAAnrnOUaPU5n52ppazDYE",
    23: "CAACAgEAAxkBAAEN-WJnx5p5sIHN2MIhmOjWfy8HWcc9zQACmwQAAs4DOUbNdleX3BsAAdA2BA",
    24: "CAACAgEAAxkBAAEN-Whnx5qVV10qc-Kb5jxTl1HeGTPw-QACPgYAAs6gOEYV-xF41uyr6jYE",
    25: "CAACAgEAAxkBAAEN-Wpnx5qgFdx2rsWhVh0uULZ17GIVzwACHgUAAj5fOEZPMrg79f8uOTYE",
    26: "CAACAgEAAxkBAAEN-Wxnx5qtDX7z_T_R0MSn_oNqH8lhAAPuBAACaKU4Rvqsbv7AX-ISNgQ",
    27: "CAACAgEAAxkBAAEN-W5nx5q5IUgPY_k-6jqt_4CaGExW_wAC2QQAAnkQOEbWUnpXp32IQzYE",
    28: "CAACAgEAAxkBAAEN-XBnx5rHP_RwOn_RLFMipINKuIwndAACIwUAAtDuOUY2TGx7FDfi-TYE",
    29: "CAACAgEAAxkBAAEN-XRnx5rYCwAB-KZz2lDyGP0NqJH1n7kAAr8EAAIZuTlGe0xGdi5QMFQ2BA",
    30: "CAACAgEAAxkBAAEN-XZnx5rkjJqxPC9RWZmzJTh42JXhBwACCwUAAqwNOEZtpWMK_3YRfDYE",
    31: "CAACAgEAAxkBAAEN-Xpnx5r4J_f0bjisycLMsIIFTGy4WAACfAkAAuAlOEZKXhvVc_7EqjYE",
    32: "CAACAgEAAxkBAAEN-Xxnx5sDpr6lLnhn-11iULGUKTMoaQACqwUAAihnOEbx393rLp-VqDYE",
    33: "CAACAgEAAxkBAAEN-X5nx5sPsjjSdNQox96V5Z326ZNYVAACOgUAAgd0OEbjDqAi9XkUKjYE",
    34: "CAACAgEAAxkBAAEN-YJnx5sk-mPZsO4meVZNzATtKirqEAACqQQAAuLFOEZAlUuADn_xTTYE",
    35: "CAACAgEAAxkBAAEN-YZnx5s3FYMz7gEUbktvThfFSF13JQACKgQAAs04OUYEZ0aclWUdPDYE",
    36: "CAACAgEAAxkBAAEN-Yhnx5tC5e8kP_hGuG0tIINShUDmHwAChQgAAlRvOEYbM-l4m5M2JjYE",
}

red_numbers = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
black_numbers = [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]

def get_multiplier(bet_type, bet_value):
    if bet_type == "number":
        return 36.0
    elif bet_type == "range":
        if bet_value in ["1-12", "13-24", "25-36"]:
            return 3.0
        elif bet_value in ["1-18", "19-36"]:
            return 2.0
    elif bet_type in ["even", "odd", "color"]:
        return 2.0
    return 0

def get_color_emoji(number):
    if number == 0:
        return "🟢"
    elif number in red_numbers:
        return "🔴"
    elif number in black_numbers:
        return "⚫"
    return ""

def get_winning_set(bet_type, bet_value):
    if bet_type == "number":
        return {int(bet_value)}
    elif bet_type == "range":
        if bet_value == "1-12":
            return set(range(1, 13))
        elif bet_value == "13-24":
            return set(range(13, 25))
        elif bet_value == "25-36":
            return set(range(25, 37))
        elif bet_value == "1-18":
            return set(range(1, 19))
        elif bet_value == "19-36":
            return set(range(19, 37))
    elif bet_type == "even":
        return set(range(2, 37, 2))
    elif bet_type == "odd":
        return set(range(1, 37, 2))
    elif bet_type == "color":
        if bet_value == "red":
            return set(red_numbers)
        elif bet_value == "black":
            return set(black_numbers)
    return set()

async def send_roulette_prompt(update, context, result_text=None, last_multiplier=None):
    game = context.user_data["roulette_game"]
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    balance = get_user_balance(user_id)
    bet_amount = game["bet_amount"]
    bet_type = game["bet_type"]
    bet_value = game["bet_value"]
    menu_state = game["menu_state"]

    if bet_type is None:
        selected_bet = "None"
        multiplier_text = ""
    else:
        if bet_type == "number":
            selected_bet = f"Number {bet_value}"
        elif bet_type == "range":
            selected_bet = bet_value
        elif bet_type == "even":
            selected_bet = "Even"
        elif bet_type == "odd":
            selected_bet = "Odd"
        elif bet_type == "color":
            selected_bet = bet_value.capitalize()
        multiplier = get_multiplier(bet_type, bet_value)
        multiplier_text = f"\nMultiplier: {multiplier:.2f}x"

    text = (
        f"🎰 Roulette\n\n"
        f"Bet: ${bet_amount:.2f}\n"
        f"Balance: ${balance:.2f}\n"
    )
    if last_multiplier is not None:
        text += f"Multiplier: {last_multiplier:.2f}x\n\n"
    if result_text:
        text += f"{result_text}\n\n"
    if not result_text:
        text += f"Selected bet: {selected_bet}{multiplier_text}\n\n"
        text += "Place your bet:"

    if menu_state == "main":
        keyboard = [
            [InlineKeyboardButton("Start", callback_data="roul_start")],
            [InlineKeyboardButton("Bet on Numbers", callback_data="roul_bet_number_menu")],
            [
                InlineKeyboardButton("1 to 12", callback_data="roul_bet_range_1-12"),
                InlineKeyboardButton("13 to 24", callback_data="roul_bet_range_13-24"),
                InlineKeyboardButton("25 to 36", callback_data="roul_bet_range_25-36"),
            ],
            [
                InlineKeyboardButton("1 to 18", callback_data="roul_bet_range_1-18"),
                InlineKeyboardButton("19 to 36", callback_data="roul_bet_range_19-36"),
            ],
            [
                InlineKeyboardButton("Even", callback_data="roul_bet_even"),
                InlineKeyboardButton("Odd", callback_data="roul_bet_odd"),
            ],
            [
                InlineKeyboardButton("🔴 Red", callback_data="roul_bet_color_red"),
                InlineKeyboardButton("⚫ Black", callback_data="roul_bet_color_black"),
            ],
            [
                InlineKeyboardButton("Bet +$1", callback_data="roul_bet_increase_1"),
                InlineKeyboardButton("Bet -$1", callback_data="roul_bet_decrease_1"),
            ],
            [InlineKeyboardButton("Cancel", callback_data="roul_cancel")]
        ]
    elif menu_state == "number_selection":
        keyboard = []
        for i in range(0, 37, 6):
            row = [InlineKeyboardButton(f"{j} {get_color_emoji(j)}", callback_data=f"roul_select_number_{j}") for j in range(i, min(i+6, 37))]
            keyboard.append(row)
        if len(keyboard[-1]) < 6:
            keyboard[-1].append(InlineKeyboardButton("Back", callback_data="roul_back"))
        else:
            keyboard.append([InlineKeyboardButton("Back", callback_data="roul_back")])

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
            message = await context.bot.send_message(chat_id=chat_id, text="Oops! Couldn’t update the game. Here’s a fresh start:", reply_markup=reply_markup)
            game["message_id"] = message.message_id
    else:
        message = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        game["message_id"] = message.message_id

async def roulette_command(update, context):
    user_id = update.effective_user.id
    if "roulette_game" in context.user_data:
        await update.message.reply_text("You already have a game running! Finish it or cancel it first.")
        return
    args = update.message.text.split()[1:]
    if not args:
        await update.message.reply_text("Please specify a bet amount, e.g., /roul 5")
        return
    try:
        bet_amount = float(args[0])
        if bet_amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Invalid bet amount. Use a positive number, e.g., /roul 5")
        return

    context.user_data["roulette_game"] = {
        "bet_amount": bet_amount,
        "bet_type": None,
        "bet_value": None,
        "multiplier": None,
        "menu_state": "main",
        "message_id": None
    }
    await send_roulette_prompt(update, context)

async def start_roulette_game(update, context):
    query = update.callback_query
    game = context.user_data["roulette_game"]
    user_id = update.effective_user.id
    bet_amount = game["bet_amount"]
    bet_type = game["bet_type"]
    bet_value = game["bet_value"]
    multiplier = game["multiplier"]

    balance = get_user_balance(user_id)
    if balance < bet_amount:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Not enough balance to place this bet!")
        del context.user_data["roulette_game"]
        return

    balance -= bet_amount
    update_user_balance(user_id, balance)

    winning_set = get_winning_set(bet_type, bet_value)
    losing_set = set(range(0, 37)) - winning_set

    if bet_amount > 100:
        spun_number = random.choice(list(losing_set)) if losing_set else random.randint(0, 36)
    else:
        N_win = len(winning_set)
        N_lose = len(losing_set)
        if N_win == 0:
            spun_number = random.choice(list(losing_set))
        elif N_lose == 0:
            spun_number = random.choice(list(winning_set))
        else:
            weights = [0.37 / N_win if num in winning_set else 0.63 / N_lose for num in range(37)]
            spun_number = random.choices(range(37), weights=weights)[0]

    if spun_number == 0:
        color = "green"
        even_odd = None
    elif spun_number in red_numbers:
        color = "red"
        even_odd = "even" if spun_number % 2 == 0 else "odd"
    elif spun_number in black_numbers:
        color = "black"
        even_odd = "even" if spun_number % 2 == 0 else "odd"

    if spun_number in stickers:
        await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=stickers[spun_number])
        await asyncio.sleep(2)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Sticker for number {spun_number} is missing!")

    win = False
    if bet_type == "number":
        win = (int(bet_value) == spun_number)
    elif bet_type == "range":
        if bet_value == "1-12":
            win = 1 <= spun_number <= 12
        elif bet_value == "13-24":
            win = 13 <= spun_number <= 24
        elif bet_value == "25-36":
            win = 25 <= spun_number <= 36
        elif bet_value == "1-18":
            win = 1 <= spun_number <= 18
        elif bet_value == "19-36":
            win = 19 <= spun_number <= 36
    elif bet_type == "even":
        win = (spun_number != 0 and even_odd == "even")
    elif bet_type == "odd":
        win = (spun_number != 0 and even_odd == "odd")
    elif bet_type == "color":
        win = (color == bet_value)

    if win:
        winnings = bet_amount * multiplier
        balance += winnings
        update_user_balance(user_id, balance)
        result_text = f"🎉 Spun: {spun_number} ({color}). You won ${winnings:.2f}"
    else:
        result_text = f"😞 Spun: {spun_number} ({color}). You lost."

    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=game["message_id"])
        game["message_id"] = None
    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Oops! Couldn’t clear the old game. Starting fresh!")
        logger.error(f"Failed to delete message: {e}")
        game["message_id"] = None

    game["bet_type"] = None
    game["bet_value"] = None
    game["multiplier"] = None

    await send_roulette_prompt(update, context, result_text=result_text, last_multiplier=multiplier)

async def roulette_button_handler(update, context):
    query = update.callback_query
    data = query.data
    if not data.startswith("roul_"):
        return
    action = data[len("roul_"):]
    game = context.user_data.get("roulette_game")
    if not game:
        return
    menu_state = game["menu_state"]

    if menu_state == "main":
        if action == "bet_number_menu":
            game["bet_type"] = None
            game["bet_value"] = None
            game["menu_state"] = "number_selection"
            await send_roulette_prompt(update, context)
        elif action.startswith("bet_range_"):
            range_str = action.split("_")[2]
            game["bet_type"] = "range"
            game["bet_value"] = range_str
            game["multiplier"] = get_multiplier("range", range_str)
            await send_roulette_prompt(update, context)
        elif action == "bet_even":
            game["bet_type"] = "even"
            game["bet_value"] = None
            game["multiplier"] = 2.0
            await send_roulette_prompt(update, context)
        elif action == "bet_odd":
            game["bet_type"] = "odd"
            game["bet_value"] = None
            game["multiplier"] = 2.0
            await send_roulette_prompt(update, context)
        elif action == "bet_color_red":
            game["bet_type"] = "color"
            game["bet_value"] = "red"
            game["multiplier"] = 2.0
            await send_roulette_prompt(update, context)
        elif action == "bet_color_black":
            game["bet_type"] = "color"
            game["bet_value"] = "black"
            game["multiplier"] = 2.0
            await send_roulette_prompt(update, context)
        elif action.startswith("bet_increase_"):
            amount = float(action.split("_")[2])
            game["bet_amount"] = max(game["bet_amount"] + amount, 1.0)
            await send_roulette_prompt(update, context)
        elif action.startswith("bet_decrease_"):
            amount = float(action.split("_")[2])
            game["bet_amount"] = max(game["bet_amount"] - amount, 1.0)
            await send_roulette_prompt(update, context)
        elif action == "start":
            if game["bet_type"] is None:
                await query.answer("Please select a bet first!", show_alert=True)
                return
            await start_roulette_game(update, context)
        elif action == "cancel":
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Game canceled!")
            del context.user_data["roulette_game"]
    elif menu_state == "number_selection":
        if action.startswith("select_number_"):
            number = action.split("_")[2]
            game["bet_type"] = "number"
            game["bet_value"] = number
            game["multiplier"] = 36.0
            game["menu_state"] = "main"
            await send_roulette_prompt(update, context)
        elif action == "back":
            game["menu_state"] = "main"
            await send_roulette_prompt(update, context)