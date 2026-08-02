from chanina.core.libretti import Libretto
from chanina.core.worker_session import WorkerSession


class FakeContext:
    def __init__(self):
        self.closed = False
        self.pages_opened = 0

    def new_page(self, **_):
        self.pages_opened += 1
        return object()

    def close(self):
        self.closed = True


class FakeCelery:
    def task(self, *_, **__):
        def decorator(func):
            return func
        return decorator


class FakeApp:
    playwright_enabled = True
    reuses_shared_context = False

    def __init__(self, context):
        self._context = context
        self.celery = FakeCelery()

    def new_context(self, **_):
        return self._context


def test_task_function_receives_a_worker_session_wrapping_the_context():
    context = FakeContext()
    app = FakeApp(context)
    received = {}

    def func(session, args):
        received["session"] = session
        return "ok"

    libretto = Libretto(app=app, func=func, title="test.session")
    libretto.task()

    assert isinstance(received["session"], WorkerSession)
    assert received["session"].browser_context is context


def test_pre_refactor_style_function_still_works_unmodified():
    """
    Simulates a libretto function written against the pre-refactor API:
    it calls session.new_page() and stores state on session.user_context,
    exactly like code written for the old WorkerSession would.
    """
    context = FakeContext()
    app = FakeApp(context)

    def legacy_style(session, args):
        session.user_context["visited"] = True
        session.new_page()
        return session.user_context["visited"]

    libretto = Libretto(app=app, func=legacy_style, title="test.legacy")
    result = libretto.task()

    assert result is True
    assert context.pages_opened == 1
    assert context.closed is True
