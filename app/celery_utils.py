try:
    from celery import Celery
except ModuleNotFoundError:
    Celery = None


class _FallbackCelery:
    class Task:
        def __call__(self, *args, **kwargs):
            raise RuntimeError('Celery is not installed in this environment.')

    def __init__(self):
        self.conf = {}
        self.Task = _FallbackCelery.Task

    def task(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator

    def send_task(self, *args, **kwargs):
        raise RuntimeError('Celery is not installed in this environment.')

def make_celery(app):
    if Celery is None:
        return _FallbackCelery()

    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL']
    )
    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery
