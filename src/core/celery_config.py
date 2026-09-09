"""Celery application configuration for distributed job execution.

Configures Celery with Redis broker, task routing, result backend,
and TLS encryption for production deployments.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import schedule

from src.core.config import get_settings
from src.core.logger import get_logger
from src.core.redis_config import get_redis_client

__all__ = ["get_celery_app"]

_logger = get_logger(__name__)


def get_celery_app() -> Celery:
    """Get or create the Celery application instance.

    Configures Celery with:
    - Redis broker from redis_config
    - Task serialization with JSON
    - Result backend for job tracking
    - Task routing by queue
    - TLS encryption in production

    Returns:
        Configured Celery app instance.
    """
    settings = get_settings()
    redis_settings = get_redis_client().connection_pool.connection_kwargs

    app = Celery("rankuno")

    # Broker configuration (Redis)
    broker_url = _build_broker_url(redis_settings)
    app.conf.broker_url = broker_url
    app.conf.broker_connection_retry_on_startup = True

    # Result backend (Redis)
    result_backend_url = _build_result_backend_url(redis_settings)
    app.conf.result_backend = result_backend_url

    # Task serialization
    app.conf.task_serializer = "json"
    app.conf.accept_content = ["json"]
    app.conf.result_serializer = "json"
    app.conf.timezone = "UTC"
    app.conf.enable_utc = True

    # Task configuration
    app.conf.task_track_started = True
    app.conf.task_time_limit = 12 * 3600  # 12 hours hard limit
    app.conf.task_soft_time_limit = 11 * 3600  # 11 hours soft limit

    # Task routing
    app.conf.task_routes = {
        "src.workers.job_executor.execute_crawl": {"queue": "crawl"},
        "src.workers.job_executor.recover_job": {"queue": "recovery"},
    }

    # Default queue
    app.conf.task_default_queue = "crawl"
    app.conf.task_default_routing_key = "crawl"
    app.conf.task_default_exchange_type = "direct"

    # Queue definitions
    app.conf.task_queues = {
        "crawl": {
            "exchange": "crawl",
            "routing_key": "crawl",
            "priority": 10,
        },
        "recovery": {
            "exchange": "recovery",
            "routing_key": "recovery",
            "priority": 5,
        },
    }

    # TLS configuration (production only)
    if settings.environment.value == "production":
        app.conf.broker_use_ssl = True
        app.conf.broker_url = broker_url.replace("redis://", "rediss://")
        app.conf.result_backend = result_backend_url.replace("redis://", "rediss://")

    _logger.info(
        "celery_initialized",
        extra={
            "broker": broker_url.split("@")[-1] if "@" in broker_url else "localhost",
            "environment": settings.environment.value,
        },
    )

    return app


def _build_broker_url(redis_settings: dict) -> str:
    """Build Redis broker URL from settings.

    Args:
        redis_settings: Connection pool settings dict.

    Returns:
        Redis broker URL (e.g., redis://localhost:6379/0).
    """
    host = redis_settings.get("host", "localhost")
    port = redis_settings.get("port", 6379)
    db = redis_settings.get("db", 0)
    password = redis_settings.get("password")

    if password:
        return f"redis://:{password}@{host}:{port}/{db}"
    return f"redis://{host}:{port}/{db}"


def _build_result_backend_url(redis_settings: dict) -> str:
    """Build Redis result backend URL from settings.

    Args:
        redis_settings: Connection pool settings dict.

    Returns:
        Redis result backend URL.
    """
    # Use same settings as broker, but different DB for results
    host = redis_settings.get("host", "localhost")
    port = redis_settings.get("port", 6379)
    password = redis_settings.get("password")
    result_db = 1  # Use DB 1 for results

    if password:
        return f"redis://:{password}@{host}:{port}/{result_db}"
    return f"redis://{host}:{port}/{result_db}"
