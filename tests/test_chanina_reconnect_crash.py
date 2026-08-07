import os
from unittest.mock import patch

import pytest

from chanina.core.chanina import ChaninaApplication


def _make_app(**kwargs) -> ChaninaApplication:
    # playwright_enabled=False keeps construction light: no signal handlers
    # are registered, and nothing tries to talk to Redis or a browser.
    return ChaninaApplication(__file__, playwright_enabled=False, **kwargs)


def test_reconnect_crashes_the_parent_and_itself_by_default_when_retries_are_exhausted():
    app = _make_app()

    with patch.object(app, "_disconnect"), \
         patch.object(app, "_connect", side_effect=ConnectionError("browser is gone")), \
         patch("chanina.core.chanina.crash_process") as crash_process:
        with pytest.raises(ConnectionError):
            app._reconnect(retries=2, delay=0)

    assert crash_process.call_count == 2
    pids = [call.kwargs["pid"] for call in crash_process.call_args_list]
    assert pids == [os.getppid(), os.getpid()]


def test_reconnect_does_not_crash_when_crash_on_browser_failure_is_disabled():
    app = _make_app(crash_on_browser_failure=False)

    with patch.object(app, "_disconnect"), \
         patch.object(app, "_connect", side_effect=ConnectionError("browser is gone")), \
         patch("chanina.core.chanina.crash_process") as crash_process:
        with pytest.raises(ConnectionError):
            app._reconnect(retries=2, delay=0)

    crash_process.assert_not_called()


def test_reconnect_does_not_crash_when_a_retry_eventually_succeeds():
    app = _make_app()

    with patch.object(app, "_disconnect"), \
         patch.object(app, "_connect", side_effect=[ConnectionError("boom"), None]), \
         patch("chanina.core.chanina.crash_process") as crash_process:
        app._reconnect(retries=2, delay=0)

    crash_process.assert_not_called()


def test_reconnect_crash_path_also_applies_to_the_firefox_engine():
    app = _make_app(browser_engine="firefox")

    with patch.object(app, "_disconnect"), \
         patch.object(app, "_launch_local", side_effect=RuntimeError("no firefox binary")), \
         patch("chanina.core.chanina.crash_process") as crash_process:
        with pytest.raises(ConnectionError):
            app._reconnect(retries=2, delay=0)

    assert crash_process.call_count == 2
