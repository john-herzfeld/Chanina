import pytest

from chanina.core.worker_session import WorkerSession


class FakeContext:
    """ Stand-in for a playwright.sync_api.BrowserContext. """
    def __init__(self):
        self.closed = False
        self.new_page_calls = []

    def new_page(self, **kwargs):
        self.new_page_calls.append(kwargs)
        return f"page({kwargs})"

    def cookies(self):
        return [{"name": "sessionid", "value": "abc"}]

    def close(self):
        self.closed = True


class FakeApp:
    def __init__(self):
        self._pw = object()


def test_new_page_with_no_args_does_not_warn():
    session = WorkerSession(browser_context=FakeContext(), app=FakeApp())

    with warnings_as_errors():
        page = session.new_page()

    assert page == "page({})"


def test_new_page_with_kwargs_forwards_them():
    context = FakeContext()
    session = WorkerSession(browser_context=context, app=FakeApp())

    session.new_page(viewport={"width": 100, "height": 100})

    assert context.new_page_calls == [{"viewport": {"width": 100, "height": 100}}]


def test_new_page_with_legacy_positional_dict_warns_and_forwards():
    context = FakeContext()
    session = WorkerSession(browser_context=context, app=FakeApp())

    with pytest.warns(DeprecationWarning):
        session.new_page({"viewport": {"width": 50, "height": 50}})

    assert context.new_page_calls == [{"viewport": {"width": 50, "height": 50}}]


def test_getattr_proxies_to_the_wrapped_context():
    context = FakeContext()
    session = WorkerSession(browser_context=context, app=FakeApp())

    assert session.cookies() == [{"name": "sessionid", "value": "abc"}]


def test_user_context_is_a_fresh_dict_per_session():
    session_a = WorkerSession(browser_context=FakeContext(), app=FakeApp())
    session_b = WorkerSession(browser_context=FakeContext(), app=FakeApp())

    session_a.user_context["key"] = "value"

    assert session_b.user_context == {}


def test_playwright_property_warns_and_returns_the_apps_driver():
    app = FakeApp()
    session = WorkerSession(browser_context=FakeContext(), app=app)

    with pytest.warns(DeprecationWarning):
        driver = session.playwright

    assert driver is app._pw


def test_close_warns_and_closes_the_wrapped_context():
    context = FakeContext()
    session = WorkerSession(browser_context=context, app=FakeApp())

    with pytest.warns(DeprecationWarning):
        session.close()

    assert context.closed is True


def test_close_is_idempotent_even_if_the_context_raises():
    class RaisingContext(FakeContext):
        def close(self):
            raise RuntimeError("already closed")

    session = WorkerSession(browser_context=RaisingContext(), app=FakeApp())

    with pytest.warns(DeprecationWarning):
        session.close()  # must not raise


def test_isinstance_check_still_works_like_before_the_refactor():
    session = WorkerSession(browser_context=FakeContext(), app=FakeApp())
    assert isinstance(session, WorkerSession)


class FakePage:
    def __init__(self):
        self._closed = False
        self.close_calls = 0

    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self.close_calls += 1
        self._closed = True


class FakeContextWithPages:
    def __init__(self):
        self.new_page_calls = 0

    def new_page(self, **kwargs):
        self.new_page_calls += 1
        return FakePage()


def test_new_page_tracks_the_page_it_opened():
    session = WorkerSession(browser_context=FakeContextWithPages(), app=FakeApp())

    page = session.new_page()

    assert session._opened_pages == [page]


def test_close_opened_pages_closes_every_still_open_page():
    session = WorkerSession(browser_context=FakeContextWithPages(), app=FakeApp())
    page_a = session.new_page()
    page_b = session.new_page()

    session._close_opened_pages()

    assert page_a.close_calls == 1
    assert page_b.close_calls == 1
    assert session._opened_pages == []


def test_close_opened_pages_skips_a_page_already_closed():
    session = WorkerSession(browser_context=FakeContextWithPages(), app=FakeApp())
    page = session.new_page()
    page.close()

    session._close_opened_pages()

    assert page.close_calls == 1  # not called again


def test_close_opened_pages_does_not_raise_if_a_page_close_fails():
    class RaisingPage(FakePage):
        def close(self):
            raise RuntimeError("page crashed")

    session = WorkerSession(browser_context=FakeContextWithPages(), app=FakeApp())
    session._opened_pages.append(RaisingPage())

    session._close_opened_pages()  # must not raise

    assert session._opened_pages == []


class warnings_as_errors:
    """ Context manager: fail the test if any warning is raised inside it. """
    def __enter__(self):
        import warnings as _warnings
        self._catcher = _warnings.catch_warnings()
        self._catcher.__enter__()
        _warnings.simplefilter("error")
        return self

    def __exit__(self, *exc_info):
        return self._catcher.__exit__(*exc_info)
