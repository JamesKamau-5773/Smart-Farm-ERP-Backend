"""Celery worker entry point.

    celery -A celery_worker.celery worker --loglevel=info

Tasks import ``app.celery``, which only exists after ``create_app()`` runs, so the app is
created first and the task modules are imported afterwards to register them.
"""
from app import create_app

flask_app = create_app()

from app import celery  # noqa: E402  (set by create_app)
import app.tasks.breeding_tasks  # noqa: E402,F401  (registers tasks)
import app.tasks.genetic_tasks  # noqa: E402,F401  (registers tasks)
import app.tasks.notification_tasks  # noqa: E402,F401  (registers tasks)
