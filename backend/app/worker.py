import argparse
import logging
import time

from backend.app.db.session import SessionLocal
from backend.app.services.job_service import claim_next_job
from backend.app.services.compilation_service import compile_job


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("skillforge.worker")


def process_one_job() -> bool:
    db = SessionLocal()

    try:
        job = claim_next_job(db)

        if job is None:
            return False

        job_id = job.id
        logger.info("Processing job %s", job_id)

        compile_job(db, job_id)

        logger.info("Finished processing job %s", job_id)
        return True

    except Exception:
        logger.exception("Worker failed while processing a job")
        return False

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="SkillForge background worker")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=3.0,
        help="Seconds between queue checks",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one job and exit",
    )
    args = parser.parse_args()

    logger.info("SkillForge worker started")

    try:
        while True:
            processed = process_one_job()

            if args.once:
                break

            if not processed:
                time.sleep(args.poll_interval)

    except KeyboardInterrupt:
        logger.info("Worker stopped")


if __name__ == "__main__":
    main()
