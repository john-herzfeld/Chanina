from unittest.mock import MagicMock

from chanina.core.browser_process import _launch


def test_launch_without_profile_dir_uses_plain_launch():
    pw = MagicMock()

    handle = _launch(pw, headless=True, port=1234, profile_dir=None)

    pw.chromium.launch.assert_called_once_with(headless=True, args=["--remote-debugging-port=1234"])
    pw.chromium.launch_persistent_context.assert_not_called()
    assert handle is pw.chromium.launch.return_value


def test_launch_with_profile_dir_uses_launch_persistent_context():
    # Chromium rejects a raw '--user-data-dir' on launch(): Playwright
    # requires launch_persistent_context(user_data_dir=...) instead.
    pw = MagicMock()

    handle = _launch(pw, headless=True, port=1234, profile_dir="/some/profile")

    pw.chromium.launch_persistent_context.assert_called_once_with(
        user_data_dir="/some/profile",
        headless=True,
        args=["--remote-debugging-port=1234"],
    )
    pw.chromium.launch.assert_not_called()
    assert handle is pw.chromium.launch_persistent_context.return_value
