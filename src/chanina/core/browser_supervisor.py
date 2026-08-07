"""
BrowserSupervisor lives in the Celery main process, before the worker pool
forks. It owns the lifecycle of the shared Chromium subprocess and never
touches Playwright itself: it only spawns/monitors browser_process.py and
publishes its CDP endpoint to Redis so worker children can connect after
the fork.
"""
import logging
import subprocess
import sys
import threading
import time
from typing import Callable

from redis import Redis

from chanina.utils import crash_process


class BrowserSupervisor:
    """
    Owns the lifecycle of the shared Chromium subprocess: starting it,
    watching it stays alive, restarting it after a crash, and stopping it.
    """

    def __init__(
        self,
        redis: Redis,
        key: str,
        headless: bool = True,
        monitor_interval: float = 5.0,
        profile_dir: str | None = None,
        crash_on_failure: bool = True,
        on_fatal: Callable[[str], None] | None = None,
    ) -> None:
        """
        Args:
            redis: Client used to publish/read the browser's CDP endpoint,
                so worker children (in other processes) can find it.
            key: Redis key the CDP endpoint is published under.
            headless: Whether the browser subprocess runs headless.
            monitor_interval: Seconds between liveness checks once
                start_monitor() is running.
            profile_dir: Optional persistent profile directory forwarded to
                the browser subprocess (see ChaninaApplication's docstring).
                Since there is only ever one shared Chromium instance, this
                has no multi-process concurrency concerns.
            crash_on_failure: If the monitor thread fails to restart the
                browser subprocess, kill this (the Celery main) process
                instead of logging and retrying on the next tick - so a
                process supervisor (e.g. Kubernetes' restartPolicy) relaunches
                the whole worker rather than it silently sitting there with
                no shared browser to hand out.
            on_fatal: Called with a reason string instead of the default
                crash_process(reason) when crash_on_failure fires. Mainly
                for tests that need to observe the failure without actually
                killing the test process.
        """
        self.redis = redis
        self.key = key
        self.headless = headless
        self.monitor_interval = monitor_interval
        self.profile_dir = profile_dir
        self.crash_on_failure = crash_on_failure
        self._on_fatal = on_fatal or crash_process

        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._monitor_thread: threading.Thread | None = None
        self._monitor_stop = threading.Event()

    @property
    def cdp_endpoint(self) -> str | None:
        """ The shared browser's CDP endpoint, or None if not published. """
        value = self.redis.get(self.key)
        return value.decode() if value else None

    def start(self) -> str:
        """ Launch the browser subprocess and publish its CDP endpoint. """
        with self._lock:
            argv = [
                sys.executable, "-m", "chanina.core.browser_process",
                "1" if self.headless else "0",
                self.profile_dir or "",
            ]
            self._proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                text=True,
            )
            endpoint = self._proc.stdout.readline().strip()
            if not endpoint:
                raise RuntimeError("Browser subprocess exited before printing its CDP endpoint.")
            self.redis.set(self.key, endpoint)
            logging.info(f"Browser started, CDP endpoint published: {endpoint}")
            return endpoint

    def ensure_alive(self) -> str:
        """
        Ensure the browser this supervisor spawned is still running, and
        (re)start it otherwise. Called at worker startup and, via the
        monitor thread, to recover from a mid-run crash.
        """
        with self._lock:
            still_running = self._proc is not None and self._proc.poll() is None
        if still_running:
            return self.cdp_endpoint
        logging.warning("Browser subprocess is not running, (re)starting it.")
        return self.start()

    def start_monitor(self) -> None:
        """
        Periodically check the browser is alive, restarting it otherwise.

        If crash_on_failure is set (the default) and a restart attempt
        fails, this kills the process instead of retrying on the next
        tick - see the crash_on_failure docstring on __init__.
        """
        def _loop():
            while not self._monitor_stop.wait(self.monitor_interval):
                try:
                    self.ensure_alive()
                except Exception as e:
                    logging.error(f"BrowserSupervisor monitor failed to restart the browser: {e}")
                    if self.crash_on_failure:
                        self._on_fatal(f"Shared browser subprocess could not be restarted: {e}")
                        return

        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(target=_loop, daemon=True)
        self._monitor_thread.start()

    def stop(self) -> None:
        """ Stop the monitor thread (if running) and terminate the browser subprocess. """
        self._monitor_stop.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=self.monitor_interval + 5)
            self._monitor_thread = None

        with self._lock:
            if self._proc is None:
                return
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            self._proc = None
