from typing import Callable

from chanina.core.worker_session import WorkerSession


class Libretto:
    """
    The interface that turns a plain function into a Celery task with access
    to the shared browser.

    When ``app.playwright_enabled`` is set, the wrapped function is called
    with a browser session as its last positional argument (before the
    trailing ``args`` dict), followed by any extra positional arguments the
    task was invoked with. That session is a
    :class:`~chanina.core.worker_session.WorkerSession` wrapping a
    :class:`playwright.sync_api.BrowserContext`. Normally that context was
    created fresh for this task alone and is closed automatically once the
    task returns (successfully or not); the one exception is
    ``app.reuses_shared_context`` (firefox engine with a profile directory),
    where every task on the same worker process shares one persistent
    context that outlives any single task and is never closed here.
    """

    def __init__(
        self,
        app,
        func: Callable,
        title: str,
        **celery_kwargs
    ) -> None:
        self.app = app
        self.func = func
        self.title = title
        self.celery_kwargs = celery_kwargs
        self.task = self._register_as_task()

    def _register_as_task(self) -> Callable:
        """ Register the libretto as a Celery task and return it. """
        @self.app.celery.task(
            name=self.title,
            **self.celery_kwargs
        )
        def _task(*args, **kwargs):
            # Celery passes unfilled positional slots as None; drop those
            # rather than forwarding them to the wrapped function.
            args = tuple(arg for arg in args if arg is not None)

            if not self.app.playwright_enabled:
                return self.func(*args, kwargs) if args else self.func(kwargs)

            context = self.app.new_context(storage_state=kwargs.pop("storage_state", None))
            session = WorkerSession(browser_context=context, app=self.app)
            try:
                if args:
                    return self.func(*args, session, kwargs)
                else:
                    return self.func(session, kwargs)
            finally:
                # Closing the raw context (rather than session.close())
                # avoids tripping the deprecation warning on our own,
                # expected, end-of-task cleanup. Skipped entirely when the
                # app hands out one long-lived shared context instead of a
                # fresh one per task (see reuses_shared_context).
                if not self.app.reuses_shared_context:
                    context.close()
        return _task
