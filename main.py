import asyncio
import sqlite3
import nest_asyncio
import requests
import os
import logging
import threading
import time
import re  # For LTC address validation
from datetime import datetime, timedelta
from decimal import Decimal  # For precise monetary calculations
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from flask import Flask, request, Response

# Game imports (replace with your actual game modules)
from dice import dice_command, dice_button_handler, dice_text_handler
from tower import tower_command, tower_button_handler
from basketball import basketball_command, basketball_button_handler
from bowling import bowling_command, bowling_button_handler
from coin import coin_command, coin_button_handler
from darts import dart_command, dart_button_handler
from football import football_command, football_button_handler
from mines import mine_command, mine_button_handler
from predict import predict_command, predict_button_handler
from roulette import roulette_command, roulette_button_handler
from slots import slots_command, slots_button_handler

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Allow nested event loops
nest_asyncio.apply()

# Bot configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8118951743:AAHT6bOYhmzl98fyKXvkfvez6refrn5dOlU")
NOWPAYMENTS_API_KEY = os.environ.get("NOWPAYMENTS_API_KEY", "86WDA8Y-A7V4Y5Y-N0ETC4V-JXB03GA")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://casino-bot-41de.onrender.com")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "YourBotUsername")
OWNER_ID = int(os.environ.get("OWNER_ID", "7054186974"))

# Price cache (currency -> (price, timestamp))
price_cache = {}
CACHE_EXPIRATION_MINUTES = 10  # Increased to reduce API calls

# Fee adjustment percentage to cover NOWPayments fees (e.g., 1.5%)
FEE_ADJUSTMENT = 0.015

# Database functions
def init_db():
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                     (user_id INTEGER PRIMARY KEY, username TEXT, balance REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS pending_deposits 
                     (payment_id TEXT PRIMARY KEY, user_id INTEGER, currency TEXT)''')
        conn.commit()

def user_exists(user_id):
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        return c.fetchone() is not None

def get_user_balance(user_id):
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        return Decimal(str(result[0])) if result else Decimal('0.0')

def update_user_balance(user_id, new_balance):
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET balance = ? WHERE user_id = ?", (float(new_balance), user_id))
        conn.commit()

def add_pending_deposit(payment_id, user_id, currency):
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute("INSERT INTO pending_deposits (payment_id, user_id, currency) VALUES (?, ?, ?)",
                  (payment_id, user_id, currency))
        conn.commit()

def get_pending_deposit(payment_id):
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, currency FROM pending_deposits WHERE payment_id = ?", (payment_id,))
        return c.fetchone()

def remove_pending_deposit(payment_id):
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute("DELETE FROM pending_deposits WHERE payment_id = ?", (payment_id,))
        conn.commit()

def get_user_by_username(username):
    with sqlite3.connect('users.db') as conn:
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE LOWER(username) = LOWER(?)", (username,))
        result = c.fetchone()
        return result[0] if result else None

# Helper functions
def create_deposit_payment(user_id, currency='ltc'):
    try:
        min_deposit_usd = 1.0
        currency_price = get_currency_to_usd_price(currency)
        min_deposit_currency = min_deposit_usd / currency_price
        
        url = "https://api.nowpayments.io/v1/payment"
        headers = {"x-api-key": NOWPAYMENTS_API_KEY}
        payload = {
            "price_amount": min_deposit_currency,
            "price_currency": currency,
            "pay_currency": currency,
            "ipn_callback_url": f"{WEBHOOK_URL}/webhook",
            "order_id": f"deposit_{user_id}_{int(time.time())}",
        }
        logger.info(f"Sending deposit request for user_id: {user_id}")
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        if 'pay_address' not in data or 'payment_id' not in data:
            logger.error(f"Invalid response from NOWPayments: {data}")
            raise ValueError("Invalid response from NOWPayments")
        logger.info(f"Received deposit response for user_id: {user_id}")
        return data
    except requests.exceptions.RequestException as e:
        logger.error(f"API request failed: {e}")
        if e.response is not None:
            logger.error(f"Response content: {e.response.text}")
        raise
    except Exception as e:
        logger.error(f"Deposit creation failed: {e}")
        raise

def get_currency_to_usd_price(currency):
    """Fetch the USD price of a cryptocurrency with rate limit handling."""
    try:
        if currency in price_cache:
            price, timestamp = price_cache[currency]
            if datetime.now() - timestamp < timedelta(minutes=CACHE_EXPIRATION_MINUTES):
                logger.info(f"Using cached price for {currency}: ${price}")
                return price
            else:
                logger.info(f"Cached price for {currency} expired, fetching new price")

        currency_map = {
            'sol': 'solana',
            'usdt_trx': 'tether',
            'usdt_eth': 'tether',
            'btc': 'bitcoin',
            'eth': 'ethereum',
            'ltc': 'litecoin'
        }
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={currency_map[currency]}&vs_currencies=usd"
        response = requests.get(url)
        if response.status_code == 429:
            logger.warning("Rate limit exceeded, waiting 60 seconds before retrying")
            time.sleep(60)
            response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        price = data[currency_map[currency]]['usd']
        price_cache[currency] = (price, datetime.now())
        logger.info(f"Fetched new price for {currency}: ${price}")
        return price
    except Exception as e:
        logger.error(f"Failed to fetch {currency} price: {e}")
        if currency in price_cache:
            price, _ = price_cache[currency]
            logger.info(f"Using last cached price for {currency}: ${price}")
            return price
        logger.info(f"No cached price for {currency}, using fallback price: $1.0")
        return 1.0

def format_expiration_time(expiration_date_str):
    try:
        expiration_time = datetime.strptime(expiration_date_str, "%Y-%m-%dT%H:%M:%S.%fZ")
        now = datetime.utcnow()
        time_left = expiration_time - now
        minutes, seconds = divmod(int(time_left.total_seconds()), 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:01d}:{minutes:02d}:{seconds:02d}"
    except:
        return "1:00:00"

# Generic game command handler
def create_game_handler(game_name, game_func):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        if not user_exists(user_id):
            await context.bot.send_message(chat_id=chat_id, text="Please register with /start first.")
            return
        if not context.args:
            text = (
                f"💣 Play {game_name.capitalize()}\n\n"
                f"To play, type the command /{game_name} with the desired bet.\n\n"
                f"Examples:\n"
                f"/{game_name} 5.50 - to play for $5.50\n"
                f"/{game_name} half - to play for half of your balance\n"
                f"/{game_name} all - to play all-in"
            )
            await context.bot.send_message(chat_id=chat_id, text=text)
            return
        bet = context.args[0].lower()
        balance = get_user_balance(user_id)
        if bet == "all":
            bet_amount = balance
        elif bet == "half":
            bet_amount = balance / 2
        else:
            try:
                bet_amount = Decimal(bet)
            except ValueError:
                await context.bot.send_message(chat_id=chat_id, text="Invalid bet amount. Please use a number, 'half', or 'all'.")
                return
        if bet_amount <= 0:
            await context.bot.send_message(chat_id=chat_id, text="Bet amount must be greater than 0.")
            return
        if bet_amount > balance:
            await context.bot.send_message(chat_id=chat_id, text="Insufficient balance.")
            return
        context.user_data['bet_amount'] = bet_amount
        await game_func(update, context)
    return handler

# Tip command handler
async def tip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not user_exists(user_id):
        await context.bot.send_message(chat_id=chat_id, text="Please register with /start first.")
        return
    if len(context.args) != 2:
        await context.bot.send_message(chat_id=chat_id, text="Usage: /tip <amount> @username")
        return
    try:
        amount = Decimal(context.args[0])
    except ValueError:
        await context.bot.send_message(chat_id=chat_id, text="Invalid amount. Please use a number.")
        return
    if amount <= 0:
        await context.bot.send_message(chat_id=chat_id, text="Tip amount must be greater than 0.")
        return
    username = context.args[1].lstrip('@')
    recipient_id = get_user_by_username(username)
    if not recipient_id:
        await context.bot.send_message(chat_id=chat_id, text=f"User @{username} not found.")
        return
    if user_id == recipient_id:
        await context.bot.send_message(chat_id=chat_id, text="You cannot tip yourself.")
        return
    balance = get_user_balance(user_id)
    if amount > balance:
        await context.bot.send_message(chat_id=chat_id, text="Insufficient balance.")
        return
    recipient_balance = get_user_balance(recipient_id)
    update_user_balance(user_id, balance - amount)
    update_user_balance(recipient_id, recipient_balance + amount)
    await context.bot.send_message(chat_id=chat_id, text=f"Successfully tipped ${amount:.2f} to @{username}.")

# Add balance command handler (owner only)
async def add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="You are not authorized to use this command.")
        return
    if len(context.args) != 2:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: /addbalance <username> <amount>")
        return
    username = context.args[0].lstrip('@')
    try:
        amount = Decimal(context.args[1])
    except ValueError:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Invalid amount. Please use a number.")
        return
    if amount <= 0:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Amount must be greater than 0.")
        return
    target_user_id = get_user_by_username(username)
    if not target_user_id:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"User @{username} not found.")
        return
    current_balance = get_user_balance(target_user_id)
    new_balance = current_balance + amount
    update_user_balance(target_user_id, new_balance)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Added ${amount:.2f} to @{username}'s balance. New balance: ${new_balance:.2f}")

# Remove balance command handler (owner only)
async def remove_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="You are not authorized to use this command.")
        return
    if len(context.args) != 2:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: /removebalance <username> <amount>")
        return
    username = context.args[0].lstrip('@')
    try:
        amount = Decimal(context.args[1])
    except ValueError:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Invalid amount. Please use a number.")
        return
    if amount <= 0:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Amount must be greater than 0.")
        return
    target_user_id = get_user_by_username(username)
    if not target_user_id:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"User @{username} not found.")
        return
    current_balance = get_user_balance(target_user_id)
    new_balance = current_balance - amount
    update_user_balance(target_user_id, new_balance)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Removed ${amount:.2f} from @{username}'s balance. New balance: ${new_balance:.2f}")
    logger.info(f"Admin removed ${amount:.2f} from @{username}'s balance. New balance: ${new_balance:.2f}")

# Withdrawal Helper Functions
def is_valid_ltc_address(address):
    """Validate Litecoin address format."""
    pattern = r'^(L|M|ltc1)[a-zA-Z0-9]{25,40}$'
    return re.match(pattern, address) is not None

def get_jwt_token():
    """Fetch a fresh JWT token from NOWPayments API."""
    url = "https://api.nowpayments.io/v1/auth"
    payload = {
        "email": os.environ.get("NOWPAYMENTS_EMAIL", "goblingoblinu@gmail.com"),
        "password": os.environ.get("NOWPAYMENTS_PASSWORD", "Melynaslaiskas1")
    }
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        if "token" in data:
            logger.info("JWT token obtained successfully")
            return data["token"]
        else:
            logger.error(f"No token found in response: {data}")
            raise Exception("No token in response")
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to get JWT token: {e}")
        if e.response is not None:
            logger.error(f"Response content: {e.response.text}")
        raise

def initiate_payout(currency, amount, address):
    """Initiate a payout via NOWPayments API with proper authentication and payload."""
    url = "https://api.nowpayments.io/v1/payout"
    try:
        token = get_jwt_token()  # Fetch a fresh token
        headers = {
            "x-api-key": NOWPAYMENTS_API_KEY,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload = {
            "withdrawals": [
                {
                    "address": address,
                    "currency": currency,
                    "amount": float(amount),
                    "ipn_callback_url": f"{WEBHOOK_URL}/payout_webhook"
                }
            ]
        }
        logger.info(f"Sending payout request for address: {address}")
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        logger.info(f"Payout successful: {data}")
        return data
    except requests.exceptions.RequestException as e:
        logger.error(f"Payout request failed: {e}")
        if e.response is not None:
            logger.error(f"Response content: {e.response.text}")
        return {"status": "error", "message": str(e)}

# Command handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    if not user_exists(user_id):
        with sqlite3.connect('users.db') as conn:
            c = conn.cursor()
            c.execute("INSERT INTO users (user_id, username, balance) VALUES (?, ?, 0.0)", (user_id, username))
            conn.commit()
    text = (
        "📣 How To Start?\n"
        "1. Make sure you have a balance. You can deposit by entering the /balance command.\n"
        "2. Go to one of our groups in @BalticGames directory\n"
        "3. Enter the /dice command and you are ready!\n\n"
        "📣 What games can I play?\n"
        "• 🎲 Dice - /dice\n"
        "• 🎳 Bowling - /bowl\n"
        "• 🎯 Darts - /dart\n"
        "• ⚽️ Football - /football\n"
        "• 🏀 Basketball - /basketball\n"
        "• 🪙 Coinflip - /coin\n"
        "• 🎰 Slot machine - /slots\n"
        "• 🎲 Dice Prediction - /predict\n"
        "• 💣 Mines - /mine\n"
        "• 🐒 Monkey Tower - /tower\n"
        "• 🎰 Roulette  - /roul\n\n"
        "Enjoy the games! 🍀"
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not user_exists(user_id):
        await context.bot.send_message(chat_id=chat_id, text="Please register with /start first.")
        return
    balance = get_user_balance(user_id)
    text = f"Your balance: ${balance:.2f}"
    keyboard = [
        [InlineKeyboardButton("Deposit", callback_data="deposit"),
         InlineKeyboardButton("Withdraw", callback_data="withdraw")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    if data == "deposit":
        if update.effective_chat.type != 'private':
            await context.bot.send_message(chat_id=chat_id, text=f"Please start a private conversation with me to proceed with the deposit: t.me/{BOT_USERNAME}")
        else:
            text = "💳 Deposit\n\nChoose your preferred deposit method"
            keyboard = [
                [InlineKeyboardButton("SOLANA", callback_data="deposit_sol"),
                 InlineKeyboardButton("USDT TRX", callback_data="deposit_usdt_trx")],
                [InlineKeyboardButton("USDT ETH", callback_data="deposit_usdt_eth"),
                 InlineKeyboardButton("BTC", callback_data="deposit_btc")],
                [InlineKeyboardButton("ETH", callback_data="deposit_eth"),
                 InlineKeyboardButton("LTC", callback_data="deposit_ltc")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    elif data.startswith("deposit_"):
        currency = data.split("_")[1]
        try:
            payment_data = create_deposit_payment(user_id, currency)
            address = payment_data['pay_address']
            payment_id = payment_data['payment_id']
            expiration_time = payment_data.get('expiration_estimate_date', '')
            expires_in = format_expiration_time(expiration_time) if expiration_time else "1:00:00"
            add_pending_deposit(payment_id, user_id, currency)
            text = (
                f"To top up your balance, transfer the desired amount to this {currency.upper()} address.\n\n"
                "Please note:\n"
                "1. The deposit address is temporary and is only issued for 1 hour. A new one will be created after that.\n"
                "2. One address accepts only one payment.\n\n"
                f"{currency.upper()} address: {address}\n"
                f"Expires in: {expires_in}"
            )
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            error_msg = str(e)
            if "401" in error_msg:
                await context.bot.send_message(chat_id=chat_id, text="API key is invalid. Please contact support.")
            elif "400" in error_msg:
                await context.bot.send_message(chat_id=chat_id, text="Invalid request. Please try again later.")
            else:
                await context.bot.send_message(chat_id=chat_id, text=f"Failed to generate deposit address: {error_msg}. Try again or contact support.")
    elif data == "withdraw":
        if update.effective_chat.type != 'private':
            await context.bot.send_message(chat_id=chat_id, text=f"Please start a private conversation with me to proceed with the withdrawal: t.me/{BOT_USERNAME}")
        else:
            context.user_data['expecting_withdrawal_details'] = True
            await context.bot.send_message(chat_id=chat_id, text="Please enter the amount in USD and your LTC address, e.g., '9.87 LTC123...' (Note: Only Litecoin withdrawals are supported.)")
    else:
        await query.answer("Unknown action.")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private' and context.user_data.get('expecting_withdrawal_details'):
        try:
            parts = update.message.text.strip().split()
            if len(parts) < 2:
                raise ValueError("Please enter 'amount address', e.g., '9.87 LTC123...'")
            amount_usd = Decimal(parts[0])
            address = parts[1]
            currency = 'ltc'
            if not is_valid_ltc_address(address):
                await context.bot.send_message(chat_id=update.effective_chat.id, text="Invalid LTC address. Please check and try again.")
                return
            balance = get_user_balance(update.effective_user.id)
            if amount_usd > balance:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="Insufficient balance for withdrawal.")
                return
            ltc_price_usd = get_currency_to_usd_price(currency)
            if ltc_price_usd == 0:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="Failed to fetch LTC price. Try again later.")
                return
            ltc_amount = float(amount_usd / Decimal(str(ltc_price_usd)))
            payout_response = initiate_payout(currency, ltc_amount, address)
            if payout_response.get('status') == 'error':
                error_msg = payout_response.get('message', 'Unknown error')
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Withdrawal failed: {error_msg}. Please check your API key or contact support.")
            else:
                new_balance = balance - amount_usd
                update_user_balance(update.effective_user.id, new_balance)
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Your withdrawal of ${amount_usd:.2f} to {address} was successful! New balance: ${new_balance:.2f}")
            context.user_data['expecting_withdrawal_details'] = False
        except ValueError as ve:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=str(ve))
        except Exception as e:
            logger.error(f"Withdrawal error: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text="An error occurred. Please try again later or contact support.")
    else:
        await dice_text_handler(update, context)

async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Unhandled update: {update}")

# Flask app for webhooks
app = Flask(__name__)

@app.route('/telegram-webhook', methods=['POST'])
def telegram_webhook():
    update = Update.de_json(request.get_json(force=True), app.bot)
    asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
    return Response(status=200)

@app.route('/webhook', methods=['POST'])
def nowpayments_webhook():
    data = request.json
    logger.info(f"NOWPayments Webhook received: {data}")
    if data.get('payment_status') == 'finished':
        payment_id = data['payment_id']
        amount_paid = float(data.get('actually_paid', data.get('pay_amount', 0)))
        currency = data.get('pay_currency')
        if amount_paid > 0:
            deposit = get_pending_deposit(payment_id)
            if deposit:
                user_id, _ = deposit
                try:
                    adjusted_amount = amount_paid * (1 - FEE_ADJUSTMENT)
                    crypto_price_usd = get_currency_to_usd_price(currency)
                    usd_amount = Decimal(str(adjusted_amount * crypto_price_usd)).quantize(Decimal('0.01'))
                    current_balance = get_user_balance(user_id)
                    new_balance = current_balance + usd_amount
                    update_user_balance(user_id, new_balance)
                    remove_pending_deposit(payment_id)
                    logger.info(f"Processing deposit: {amount_paid} {currency} (adjusted to {adjusted_amount}) = ${usd_amount}")
                    asyncio.run_coroutine_threadsafe(
                        app.bot.send_message(
                            chat_id=user_id,
                            text=f"✅ Deposit of {amount_paid} {currency.upper()} received! "
                                 f"Credited ${usd_amount:.2f} after fees. New balance: ${new_balance:.2f}"
                        ),
                        loop
                    )
                except Exception as e:
                    logger.error(f"Failed to process deposit: {e}")
    return Response(status=200)

def run_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

async def main():
    global application, loop
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()
    await application.initialize()
    app.bot = application.bot

    # Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("balance", balance_command))
    
    # Register game command handlers with bet logic
    application.add_handler(CommandHandler("dice", create_game_handler("dice", dice_command)))
    application.add_handler(CommandHandler("tower", create_game_handler("tower", tower_command)))
    application.add_handler(CommandHandler("basketball", create_game_handler("basketball", basketball_command)))
    application.add_handler(CommandHandler("bowl", create_game_handler("bowl", bowling_command)))
    application.add_handler(CommandHandler("coin", create_game_handler("coin", coin_command)))
    application.add_handler(CommandHandler("dart", create_game_handler("dart", dart_command)))
    application.add_handler(CommandHandler("football", create_game_handler("football", football_command)))
    application.add_handler(CommandHandler("mine", create_game_handler("mine", mine_command)))
    application.add_handler(CommandHandler("predict", create_game_handler("predict", predict_command)))
    application.add_handler(CommandHandler("roul", create_game_handler("roul", roulette_command)))
    application.add_handler(CommandHandler("slots", create_game_handler("slots", slots_command)))

    # Register tip command
    application.add_handler(CommandHandler("tip", tip_command))

    # Register addbalance and removebalance commands (owner only)
    application.add_handler(CommandHandler("addbalance", add_balance_command))
    application.add_handler(CommandHandler("removebalance", remove_balance_command))

    # Register game button handlers FIRST
    application.add_handler(CallbackQueryHandler(dice_button_handler, pattern="^dice_"))
    application.add_handler(CallbackQueryHandler(tower_button_handler, pattern="^tower_"))
    application.add_handler(CallbackQueryHandler(basketball_button_handler, pattern="^basketball_"))
    application.add_handler(CallbackQueryHandler(bowling_button_handler, pattern="^bowl_"))
    application.add_handler(CallbackQueryHandler(coin_button_handler, pattern="^coin_"))
    application.add_handler(CallbackQueryHandler(dart_button_handler, pattern="^dart_"))
    application.add_handler(CallbackQueryHandler(football_button_handler, pattern="^tower_"))
    application.add_handler(CallbackQueryHandler(mine_button_handler, pattern="^mine_"))
    application.add_handler(CallbackQueryHandler(predict_button_handler, pattern="^predict_"))
    application.add_handler(CallbackQueryHandler(roulette_button_handler, pattern="^roul_"))
    application.add_handler(CallbackQueryHandler(slots_button_handler, pattern="^slots_"))

    # Then, register the general button handler
    application.add_handler(CallbackQueryHandler(button_handler))

    # Register text handler for withdrawal and dice username input
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Fallback handler
    application.add_handler(MessageHandler(filters.ALL, fallback_handler))

    loop = asyncio.new_event_loop()
    threading.Thread(target=run_loop, args=(loop,), daemon=True).start()
    await application.bot.set_webhook(url=f"{WEBHOOK_URL}/telegram-webhook")
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Flask app on port {port}...")
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    asyncio.run(main())
