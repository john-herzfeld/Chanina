from unittest.mock import MagicMock, patch

from chanina.core.browser_supervisor import BrowserSupervisor


class FakeRedis:
    def __init__(self):
        self._store = {}

    def get(self, key):
        value = self._store.get(key)
        return value.encode() if isinstance(value, str) else value

    def set(self, key, value):
        self._store[key] = value


def _fake_proc(endpoint: str):
    proc = MagicMock()
    proc.stdout.readline.return_value = f"{endpoint}\n"
    proc.poll.return_value = None
    return proc


def test_ensure_alive_starts_the_browser_once():
    redis = FakeRedis()
    supervisor = BrowserSupervisor(redis=redis, key="chanina:test:endpoint")
    proc = _fake_proc("http://127.0.0.1:1111")

    with patch("chanina.core.browser_supervisor.subprocess.Popen", return_value=proc) as popen:
        first = supervisor.ensure_alive()
        second = supervisor.ensure_alive()

    assert first == "http://127.0.0.1:1111"
    assert second == "http://127.0.0.1:1111"
    popen.assert_called_once()
    assert redis.get("chanina:test:endpoint").decode() == "http://127.0.0.1:1111"


def test_ensure_alive_restarts_and_republishes_after_a_crash():
    redis = FakeRedis()
    supervisor = BrowserSupervisor(redis=redis, key="chanina:test:endpoint")

    first_proc = _fake_proc("http://127.0.0.1:1111")
    second_proc = _fake_proc("http://127.0.0.1:2222")

    with patch(
        "chanina.core.browser_supervisor.subprocess.Popen",
        side_effect=[first_proc, second_proc],
    ):
        endpoint = supervisor.ensure_alive()
        assert endpoint == "http://127.0.0.1:1111"

        # Simulate the browser subprocess crashing.
        first_proc.poll.return_value = 1

        endpoint = supervisor.ensure_alive()

    assert endpoint == "http://127.0.0.1:2222"
    assert redis.get("chanina:test:endpoint").decode() == "http://127.0.0.1:2222"


def test_start_forwards_the_profile_dir_to_the_subprocess():
    redis = FakeRedis()
    supervisor = BrowserSupervisor(redis=redis, key="chanina:test:endpoint", profile_dir="/some/profile")
    proc = _fake_proc("http://127.0.0.1:1111")

    with patch("chanina.core.browser_supervisor.subprocess.Popen", return_value=proc) as popen:
        supervisor.start()

    argv = popen.call_args.args[0]
    assert argv[-1] == "/some/profile"


def test_start_forwards_an_empty_profile_dir_by_default():
    redis = FakeRedis()
    supervisor = BrowserSupervisor(redis=redis, key="chanina:test:endpoint")
    proc = _fake_proc("http://127.0.0.1:1111")

    with patch("chanina.core.browser_supervisor.subprocess.Popen", return_value=proc) as popen:
        supervisor.start()

    argv = popen.call_args.args[0]
    assert argv[-1] == ""


def test_stop_terminates_the_running_process():
    redis = FakeRedis()
    supervisor = BrowserSupervisor(redis=redis, key="chanina:test:endpoint")
    proc = _fake_proc("http://127.0.0.1:1111")

    with patch("chanina.core.browser_supervisor.subprocess.Popen", return_value=proc):
        supervisor.ensure_alive()

    supervisor.stop()

    proc.terminate.assert_called_once()
    proc.wait.assert_called_once()
