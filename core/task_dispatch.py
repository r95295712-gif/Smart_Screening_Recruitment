import threading

from django.conf import settings
from django.db import close_old_connections

_local_task_lock = threading.Lock()


def _run_local_task(task, args, kwargs):
    with _local_task_lock:
        close_old_connections()
        try:
            task.run(*args, **kwargs)
        finally:
            close_old_connections()


def dispatch_task(task, *args, **kwargs):
    if settings.LOCAL_BACKGROUND_TASKS:
        thread = threading.Thread(
            target=_run_local_task,
            args=(task, args, kwargs),
            daemon=True,
            name=f"local-task-{task.name}",
        )
        thread.start()
        return thread
    return task.delay(*args, **kwargs)
