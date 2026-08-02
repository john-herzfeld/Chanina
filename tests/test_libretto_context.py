import pytest

from chanina.core.libretti import Libretto


class FakeContext:
    def __init__(self):
        self.closed = False

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


def test_context_is_closed_when_the_task_succeeds():
    context = FakeContext()
    app = FakeApp(context)

    libretto = Libretto(app=app, func=lambda ctx, args: "ok", title="test.ok")

    result = libretto.task()

    assert result == "ok"
    assert context.closed is True


def test_context_is_closed_even_when_the_task_raises():
    context = FakeContext()
    app = FakeApp(context)

    def failing(ctx, args):
        raise ValueError("boom")

    libretto = Libretto(app=app, func=failing, title="test.failing")

    with pytest.raises(ValueError):
        libretto.task()

    assert context.closed is True


def test_shared_context_is_never_closed_by_libretto():
    context = FakeContext()
    app = FakeApp(context)
    app.reuses_shared_context = True

    libretto = Libretto(app=app, func=lambda ctx, args: "ok", title="test.shared")

    libretto.task()
    libretto.task()

    assert context.closed is False
