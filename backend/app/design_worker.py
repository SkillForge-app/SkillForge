import logging

from rq import SimpleWorker

from backend.app.queues import redis_connection, skills_queue


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("skillforge.design_worker")


def main() -> None:
    logger.info("SkillForge Design Worker started")

    worker = SimpleWorker(
        [skills_queue],
        connection=redis_connection,
    )

    worker.work()


if __name__ == "__main__":
    main()