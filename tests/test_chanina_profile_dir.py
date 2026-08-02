from unittest.mock import MagicMock, patch

from chanina.core.chanina import ChaninaApplication


def _make_app(**kwargs) -> ChaninaApplication:
    return ChaninaApplication(__file__, playwright_enabled=False, browser_engine="firefox", **kwargs)


def test_launch_local_uses_a_plain_browser_without_a_profile_dir():
    app = _make_app()
    fake_pw = MagicMock()

    with patch("chanina.core.chanina.sync_playwright", return_value=MagicMock(start=lambda: fake_pw)):
        app._launch_local()

    fake_pw.firefox.launch.assert_called_once_with(headless=True)
    fake_pw.firefox.launch_persistent_context.assert_not_called()
    assert app.reuses_shared_context is False


def test_launch_local_uses_a_persistent_context_with_a_profile_dir(tmp_path):
    # Playwright rejects a raw '-profile' CLI arg on launch(); the profile
    # must go through launch_persistent_context(user_data_dir=...) instead.
    profile_dir = tmp_path / "my-profile"
    app = _make_app(profile_dir=str(profile_dir))
    fake_pw = MagicMock()

    with patch("chanina.core.chanina.sync_playwright", return_value=MagicMock(start=lambda: fake_pw)):
        app._launch_local()

    fake_pw.firefox.launch_persistent_context.assert_called_once_with(
        user_data_dir=str(profile_dir), headless=True,
    )
    fake_pw.firefox.launch.assert_not_called()
    assert profile_dir.is_dir()
    assert app.reuses_shared_context is True


def test_new_context_returns_the_same_shared_context_every_call_in_shared_mode():
    app = _make_app()
    shared_context = MagicMock()
    app._browser = shared_context
    app._shared_context_mode = True
    app._playwright_enabled = True

    first = app.new_context(storage_state=None)
    second = app.new_context(storage_state=None)

    assert first is shared_context
    assert second is shared_context
    shared_context.new_context.assert_not_called()


def test_new_context_creates_a_fresh_context_per_call_without_profile():
    app = _make_app()
    browser = MagicMock()
    app._browser = browser
    app._playwright_enabled = True

    app.new_context(storage_state=None)

    browser.new_context.assert_called_once_with(storage_state=None)
