from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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


def test_launch_local_copies_an_existing_profile_dir_instead_of_using_it_directly(tmp_path):
    profile_dir = tmp_path / "existing-profile"
    profile_dir.mkdir()
    (profile_dir / "cookies.sqlite").write_text("existing session data")

    app = _make_app(profile_dir=str(profile_dir))
    fake_pw = MagicMock()

    with patch("chanina.core.chanina.sync_playwright", return_value=MagicMock(start=lambda: fake_pw)):
        app._launch_local()

    used_dir = fake_pw.firefox.launch_persistent_context.call_args.kwargs["user_data_dir"]
    assert used_dir != str(profile_dir)
    assert (Path(used_dir) / "cookies.sqlite").read_text() == "existing session data"
    assert app._local_profile_copy == (used_dir, True)

    app._disconnect()

    assert not Path(used_dir).exists()
    assert profile_dir.exists()
    assert (profile_dir / "cookies.sqlite").exists()


def test_new_context_returns_the_same_shared_context_every_call_in_shared_mode():
    app = _make_app()
    shared_context = MagicMock()
    app._browser = shared_context
    app._shared_context = shared_context
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


def _make_chromium_app(**kwargs) -> ChaninaApplication:
    return ChaninaApplication(__file__, playwright_enabled=False, browser_engine="chromium", **kwargs)


def test_connect_reuses_the_browsers_existing_context_with_a_profile_dir(tmp_path):
    app = _make_chromium_app(profile_dir=str(tmp_path))
    app._redis = MagicMock()
    app._redis.get.return_value = b"http://127.0.0.1:1234"
    profile_context = MagicMock()
    fake_pw = MagicMock()
    fake_pw.chromium.connect_over_cdp.return_value = MagicMock(contexts=[profile_context])

    with patch("chanina.core.chanina.sync_playwright", return_value=MagicMock(start=lambda: fake_pw)):
        app._connect()

    assert app._shared_context is profile_context
    assert app.reuses_shared_context is True


def test_connect_creates_fresh_contexts_per_task_without_a_profile_dir():
    app = _make_chromium_app()
    app._redis = MagicMock()
    app._redis.get.return_value = b"http://127.0.0.1:1234"
    fake_pw = MagicMock()
    fake_pw.chromium.connect_over_cdp.return_value = MagicMock(contexts=[])

    with patch("chanina.core.chanina.sync_playwright", return_value=MagicMock(start=lambda: fake_pw)):
        app._connect()

    assert app._shared_context is None
    assert app.reuses_shared_context is False


def test_connect_with_a_profile_dir_but_no_existing_context_raises(tmp_path):
    # If this ever happens it means browser_process.py's persistent
    # context vanished unexpectedly; fail loudly instead of silently
    # falling back to an unrelated, profile-less context.
    app = _make_chromium_app(profile_dir=str(tmp_path))
    app._redis = MagicMock()
    app._redis.get.return_value = b"http://127.0.0.1:1234"
    fake_pw = MagicMock()
    fake_pw.chromium.connect_over_cdp.return_value = MagicMock(contexts=[])

    with patch("chanina.core.chanina.sync_playwright", return_value=MagicMock(start=lambda: fake_pw)):
        with pytest.raises(RuntimeError):
            app._connect()


def test_on_worker_init_forwards_a_copy_of_an_existing_profile_dir_to_the_supervisor(tmp_path):
    profile_dir = tmp_path / "existing-profile"
    profile_dir.mkdir()
    (profile_dir / "cookies.sqlite").write_text("existing session data")

    app = _make_chromium_app(profile_dir=str(profile_dir))
    app._redis = MagicMock()

    fake_supervisor = MagicMock()
    with patch("chanina.core.chanina.BrowserSupervisor", return_value=fake_supervisor) as supervisor_cls:
        app._on_worker_init()

    used_dir = supervisor_cls.call_args.kwargs["profile_dir"]
    assert used_dir != str(profile_dir)
    assert (Path(used_dir) / "cookies.sqlite").read_text() == "existing session data"
    assert app._shared_profile_copy == (used_dir, True)
    fake_supervisor.ensure_alive.assert_called_once()
    fake_supervisor.start_monitor.assert_called_once()

    app._on_worker_shutdown()

    assert not Path(used_dir).exists()
    assert profile_dir.exists()
    assert app._shared_profile_copy is None


def test_on_worker_init_uses_a_fresh_profile_dir_as_is(tmp_path):
    profile_dir = tmp_path / "brand-new-profile"

    app = _make_chromium_app(profile_dir=str(profile_dir))
    app._redis = MagicMock()

    fake_supervisor = MagicMock()
    with patch("chanina.core.chanina.BrowserSupervisor", return_value=fake_supervisor) as supervisor_cls:
        app._on_worker_init()

    assert supervisor_cls.call_args.kwargs["profile_dir"] == str(profile_dir)
    assert app._shared_profile_copy == (str(profile_dir), False)

    app._on_worker_shutdown()

    # Not a copy, so it's the template left behind for next time - not deleted.
    assert profile_dir.exists()
