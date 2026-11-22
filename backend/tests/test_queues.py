from backend.app.queues import redis_connection, skills_queue


def test_skills_queue_configuration():
    assert skills_queue.name == "skills"
    assert skills_queue.connection is redis_connection
    assert redis_connection.connection_pool.connection_kwargs["db"] == 0
