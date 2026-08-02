import logging

from chanina.default_libretti import build_default_libretti


class FakeApp:
    def __init__(self):
        self.libretti = {}

    def libretto(self, title):
        def decorator(func):
            self.libretti[title] = func
            return func
        return decorator


class FakeSession:
    def __init__(self, raise_on_new_page=False):
        self.new_page_called = False
        self._raise = raise_on_new_page

    def new_page(self):
        self.new_page_called = True
        if self._raise:
            raise RuntimeError("no browser available")


def test_registers_the_two_reserved_libretti():
    app = FakeApp()
    build_default_libretti(app)
    assert set(app.libretti) == {"chanina.list_libretti", "chanina.new_page"}


def test_chanina_new_page_opens_a_page_on_the_injected_session():
    app = FakeApp()
    build_default_libretti(app)
    session = FakeSession()

    app.libretti["chanina.new_page"](session, {})

    assert session.new_page_called is True


def test_chanina_new_page_is_a_noop_without_a_session():
    app = FakeApp()
    build_default_libretti(app)

    app.libretti["chanina.new_page"]()  # must not raise


def test_chanina_new_page_swallows_errors_from_the_session(caplog):
    app = FakeApp()
    build_default_libretti(app)
    session = FakeSession(raise_on_new_page=True)

    with caplog.at_level(logging.ERROR):
        app.libretti["chanina.new_page"](session, {})  # must not raise

    assert "Failed to open a new page" in caplog.text


def test_chanina_list_libretti_logs_the_registered_libretti(caplog):
    app = FakeApp()
    build_default_libretti(app)

    with caplog.at_level(logging.INFO):
        app.libretti["chanina.list_libretti"]()

    assert "chanina.list_libretti" in caplog.text
