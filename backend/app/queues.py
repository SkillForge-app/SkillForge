from redis import Redis
from rq import Queue

from backend.app.core.config import settings


redis_connection = Redis.from_url(
    settings.REDIS_URL,
    decode_responses=False,
)

skills_queue = Queue(
    "skills",
    connection=redis_connection,
    default_timeout=300,
)
