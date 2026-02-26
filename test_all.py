import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

from db.base import Base
from db.connection import engine, get_session
from discovery.hashtag import discover_hashtag
from discovery.keyword import discover_keyword
from discovery.creator import discover_creator_reels

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    Base.metadata.create_all(bind=engine)
    logger.info("Database ready.")

    with get_session() as session:
        try:
            logger.info("--- Testing HASHTAG Discovery (#coding) ---")
            await discover_hashtag(
                session=session, hashtag="coding", limit=2, account_id="test_account"
            )

            logger.info("--- Testing CREATOR Discovery (@zuck) ---")
            await discover_creator_reels(
                session=session, username="zuck", limit=2, account_id="test_account"
            )

            logger.info("--- Testing KEYWORD Discovery ('python programming') ---")
            logger.info(
                "Note: For keywords, the script will wait while YOU search/scroll manually in the Chromium window."
            )
            await discover_keyword(
                session=session,
                keyword="python programming",
                limit=2,
                account_id="test_account",
            )

            logger.info("🎉 All discovery scrapers executed successfully!")
        except Exception as e:
            logger.error("Test failed: %s", e)


if __name__ == "__main__":
    asyncio.run(main())
