import asyncio
import logging
import os
from dotenv import load_dotenv

# Ensure environment variables are loaded before imports
load_dotenv()

from db.base import Base
from db.connection import engine, get_session
from discovery.trending import discover_trending

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Setting up database tables if they don't exist...")
    # This creates tables based on our SQLAlchemy models
    Base.metadata.create_all(bind=engine)

    logger.info("Database ready. Connecting to PostgreSQL...")

    # Open a DB session and run the trending scraper
    with get_session() as session:
        logger.info("Starting trending discovery scraper. Max 5 reels to test...")
        # Limiting to 5 to quickly verify end-to-end functionality
        try:
            await discover_trending(session=session, limit=5, account_id="test_account")
            logger.info(
                "Module 1 Test Complete! Check your database to verify the ingested reels."
            )
        except Exception as e:
            logger.error("Test failed: %s", e)


if __name__ == "__main__":
    # Ensure Playwright dependencies are installed:
    # pip install playwright psycopg2-binary SQLAlchemy python-dotenv
    # playwright install chromium
    asyncio.run(main())
