import logging
import asyncio
import telegram.error

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def send_with_retry(bot, chat_id, text=None, emoji=None, reply_markup=None, reply_to_message_id=None, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            if text is not None:
                return await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    reply_to_message_id=reply_to_message_id,
                    **kwargs
                )
            elif emoji is not None:
                return await bot.send_dice(
                    chat_id=chat_id,
                    emoji=emoji,
                    reply_to_message_id=reply_to_message_id,
                    **kwargs
                )
        except telegram.error.TimedOut:
            logger.warning("Timeout occurred. Retrying in 5 seconds...")
            await asyncio.sleep(5)
        except telegram.error.RetryAfter as e:
            wait_time = e.retry_after
            logger.warning(f"Rate limit hit. Waiting {wait_time} seconds...")
            await asyncio.sleep(wait_time)
        except Exception as e:
            logger.error(f"Error: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(1 * (2 ** attempt))
    logger.error("Failed after retries.")
    return None