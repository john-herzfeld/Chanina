import time
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


def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met in time")


def test_monitor_crashes_by_default_when_a_restart_attempt_fails():
    redis = FakeRedis()
    proc = _fake_proc("http://127.0.0.1:1111")
    fatal_calls = []

    supervisor = BrowserSupervisor(
        redis=redis,
        key="chanina:test:endpoint",
        monitor_interval=0.01,
        on_fatal=fatal_calls.append,
    )

    with patch(
        "chanina.core.browser_supervisor.subprocess.Popen",
        side_effect=[proc, RuntimeError("boom")],
    ):
        supervisor.ensure_alive()
        proc.poll.return_value = 1  # simulate the browser subprocess dying
        supervisor.start_monitor()
        _wait_for(lambda: fatal_calls)

    supervisor.stop()
    assert len(fatal_calls) == 1
    assert "boom" in fatal_calls[0]


def test_monitor_only_crashes_once_even_if_stop_is_slow():
    redis = FakeRedis()
    proc = _fake_proc("http://127.0.0.1:1111")
    fatal_calls = []

    supervisor = BrowserSupervisor(
        redis=redis,
        key="chanina:test:endpoint",
        monitor_interval=0.01,
        on_fatal=fatal_calls.append,
    )

    with patch(
        "chanina.core.browser_supervisor.subprocess.Popen",
        side_effect=[proc, RuntimeError("boom")],
    ):
        supervisor.ensure_alive()
        proc.poll.return_value = 1
        supervisor.start_monitor()
        _wait_for(lambda: fatal_calls)
        time.sleep(0.05)  # give the loop a few more ticks it should not take

    supervisor.stop()
    assert len(fatal_calls) == 1


def test_monitor_does_not_crash_when_crash_on_failure_is_disabled():
    redis = FakeRedis()
    proc = _fake_proc("http://127.0.0.1:1111")
    fatal_calls = []

    supervisor = BrowserSupervisor(
        redis=redis,
        key="chanina:test:endpoint",
        monitor_interval=0.01,
        crash_on_failure=False,
        on_fatal=fatal_calls.append,
    )

    with patch(
        "chanina.core.browser_supervisor.subprocess.Popen",
        side_effect=[proc] + [RuntimeError("boom")] * 5,
    ):
        supervisor.ensure_alive()
        proc.poll.return_value = 1
        supervisor.start_monitor()
        time.sleep(0.1)

    supervisor.stop()
    assert fatal_calls == []


def test_default_on_fatal_is_crash_process():
    redis = FakeRedis()
    proc = _fake_proc("http://127.0.0.1:1111")

    # crash_process must be patched *before* the supervisor is constructed:
    # __init__ resolves the default on_fatal callback (on_fatal or
    # crash_process) eagerly, so patching afterwards would leave the real,
    # SIGKILL-ing crash_process bound instead of the mock.
    with patch(
        "chanina.core.browser_supervisor.subprocess.Popen",
        side_effect=[proc, RuntimeError("boom")],
    ), patch("chanina.core.browser_supervisor.crash_process") as crash_process:
        supervisor = BrowserSupervisor(redis=redis, key="chanina:test:endpoint", monitor_interval=0.01)
        supervisor.ensure_alive()
        proc.poll.return_value = 1
        supervisor.start_monitor()
        _wait_for(lambda: crash_process.called)

    supervisor.stop()
    crash_process.assert_called_once()


def test_stop_terminates_the_running_process():
    redis = FakeRedis()
    supervisor = BrowserSupervisor(redis=redis, key="chanina:test:endpoint")
    proc = _fake_proc("http://127.0.0.1:1111")

    with patch("chanina.core.browser_supervisor.subprocess.Popen", return_value=proc):
        supervisor.ensure_alive()

    supervisor.stop()

    proc.terminate.assert_called_once()
    proc.wait.assert_called_once()
