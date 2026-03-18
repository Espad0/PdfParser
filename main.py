"""Entry point for the Invoice Parser Telegram Bot."""

import logging
import sys

from config import ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN.startswith("your-"):
        sys.exit("Error: TELEGRAM_BOT_TOKEN is not set. Define it in the .env file.")
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("your-"):
        sys.exit("Error: ANTHROPIC_API_KEY is not set. Define it in the .env file.")

    from bot import create_bot

    logger.info("Starting Invoice Parser Bot...")
    app = create_bot()
    app.run_polling()


if __name__ == "__main__":
    main()
