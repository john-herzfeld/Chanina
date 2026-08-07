import pytest

from chanina.core.libretti import Libretto


class FakePage:
    def __init__(self):
        self._closed = False
        self.close_calls = 0

    def is_closed(self):
        return self._closed

    def close(self):
        self.close_calls += 1
        self._closed = True


class FakeContext:
    def __init__(self):
        self.closed = False
        self.pages = []

    def close(self):
        self.closed = True

    def new_page(self, **_):
        page = FakePage()
        self.pages.append(page)
        return page


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


def test_a_page_left_open_by_a_failing_task_is_still_closed():
    context = FakeContext()
    app = FakeApp(context)

    def failing(session, args):
        session.new_page()  # left open, task blows up before closing it
        raise ValueError("boom")

    libretto = Libretto(app=app, func=failing, title="test.failing_page")

    with pytest.raises(ValueError):
        libretto.task()

    assert context.pages[0].close_calls == 1


def test_a_page_left_open_on_a_shared_context_is_still_closed_per_task():
    context = FakeContext()
    app = FakeApp(context)
    app.reuses_shared_context = True

    def failing(session, args):
        session.new_page()
        raise ValueError("boom")

    libretto = Libretto(app=app, func=failing, title="test.shared_failing_page")

    with pytest.raises(ValueError):
        libretto.task()

    # The shared context itself stays open across tasks ...
    assert context.closed is False
    # ... but the page the task opened does not leak.
    assert context.pages[0].close_calls == 1
