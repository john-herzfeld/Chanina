"""
ChaninaApplication drives the browser(s) used by Celery worker processes.

Two engines are supported:
- "chromium" (default): a single Chromium instance is shared by every
  worker process. It never lives inside this (the Celery main) process: it
  is supervised as a separate OS subprocess (see browser_process.py /
  BrowserSupervisor) so that no live Playwright/asyncio state exists here
  before the worker pool forks. Each forked worker child connects to the
  shared browser over CDP and creates one isolated BrowserContext per task
  - unless a profile_dir is set, in which case every task instead reuses
  that profile's one persistent context (see reuses_shared_context).
- "firefox": Playwright's Python bindings have no supported way to share a
  Firefox instance across OS processes (no launch_server()/connect() pair
  outside Node.js, and connect_over_cdp() only works against Chromium).
  Each worker process launches and owns its own local Firefox instead, the
  same 1-browser-per-worker-process model as before this refactor. A given
  profile directory can only be opened by one running Firefox at a time,
  so chanina.__main__.run_worker forces concurrency=1 for this engine.

Whenever profile_dir is set, for either engine, the directory actually
handed to the browser is a disposable copy of it made under the system
temp dir (see chanina.utils.prepare_profile_dir), never profile_dir
itself - profile_dir is treated as a read-only template.
"""
import logging
import time
import warnings
from pathlib import Path
from typing import Callable

from celery import Celery, signals
from playwright.sync_api import BrowserContext, Playwright, sync_playwright
from redis import Redis

from chanina.core.browser_supervisor import BrowserSupervisor
from chanina.core.libretti import Libretto
from chanina.default_libretti import build_default_libretti
from chanina.utils import cleanup_profile_dir, prepare_profile_dir

# Pre-refactor 'browser_name' values ("firefox" or "chrome") mapped onto the
# current 'browser_engine' values ("firefox" or "chromium").
_LEGACY_BROWSER_NAME_MAP = {"firefox": "firefox", "chrome": "chromium"}


class ChaninaApplication:
    """ Chanina application object. """
    def __init__(
        self,
        caller_path: str,
        backend: str = "redis://localhost:6379",
        broker: str = "amqp://localhost:5672",
        redis_host: str = "localhost",
        redis_port: int = 6379,
        playwright_enabled: bool = True,
        headless: bool = True,
        browser_engine: str | None = None,
        celery_config: dict = {},
        profile_dir: str | None = None,
        *,
        browser_name: str | None = None,
        user_profile_path: str | None = None,
    ) -> None:
        """
        Args:
            caller_path: Path of the module instantiating this application
                (usually ``__file__``); used to derive a stable per-app key.
            backend: Celery result backend URL.
            broker: Celery broker URL.
            redis_host: Host of the Redis instance used to coordinate the
                shared browser's CDP endpoint across worker processes.
            redis_port: Port of that same Redis instance.
            playwright_enabled: Whether tasks get a browser session at all.
            headless: Whether the browser(s) run headless.
            browser_engine: ``"chromium"`` (default) for a single browser
                shared by every worker process, or ``"firefox"`` for one
                local browser per worker process. See the module docstring.
            celery_config: Extra config forwarded to ``Celery.config_from_object``.
            profile_dir: Directory holding a persistent browser profile
                (history, cookies, cache, extensions, ...), created if it
                doesn't exist yet. Treated as a read-only template: what
                the browser actually gets is a disposable copy of it made
                under the system temp dir, so profile_dir itself is never
                written to (see the module docstring). For
                ``browser_engine="chromium"`` it is used by the single
                shared browser subprocess (there is only ever one, so no
                concurrency concern). For ``browser_engine="firefox"`` it
                is used by every worker process's own local browser — a
                given profile directory can only be opened by one running
                Firefox at a time, so ``run_worker`` forces
                ``concurrency=1`` whenever this engine is used.
                A typical setup reads this from an env var in your own app
                script, e.g. ``profile_dir=os.environ.get("CHANINA_PROFILE_DIR")``.
            browser_name: Deprecated alias for ``browser_engine`` using the
                pre-refactor values ``"firefox"``/``"chrome"``. Use
                ``browser_engine`` (``"firefox"``/``"chromium"``) instead.
            user_profile_path: Deprecated alias for ``profile_dir``. Note
                the underlying mechanism changed: the old per-process,
                copy-on-init profile handling is gone, and this value is
                now used exactly like ``profile_dir`` (see above).
        """
        if browser_name is not None:
            warnings.warn(
                "'browser_name' is deprecated, use 'browser_engine' instead "
                "('chrome' -> 'chromium', 'firefox' -> 'firefox').",
                DeprecationWarning,
                stacklevel=2,
            )
            if browser_name not in _LEGACY_BROWSER_NAME_MAP:
                raise ValueError("browser_name must be 'firefox' or 'chrome'")
            if browser_engine is None:
                browser_engine = _LEGACY_BROWSER_NAME_MAP[browser_name]

        if user_profile_path is not None:
            warnings.warn(
                "'user_profile_path' is deprecated, use 'profile_dir' "
                "instead. Note the underlying mechanism changed: the old "
                "per-process, copy-on-init profile handling is gone, "
                "'profile_dir' is now used as-is (see the docstring).",
                DeprecationWarning,
                stacklevel=2,
            )
            if profile_dir is None:
                profile_dir = user_profile_path

        if browser_engine is None:
            browser_engine = "chromium"
        if browser_engine not in ("chromium", "firefox"):
            raise ValueError(f"browser_engine must be 'chromium' or 'firefox', got '{browser_engine}'.")

        # Inside the celery worker process the __file__ might be dir.module
        caller_path = str(Path(caller_path).resolve().parent)

        self._redis_host = redis_host
        self._redis_port = redis_port
        self._redis: Redis | None = None
        self._browser_key = f"chanina:browser:cdp_endpoint:{caller_path}"

        self.celery = Celery("chanina", broker=broker, backend=backend)
        self.celery.config_from_object(celery_config)

        self._libretti = {}
        self._caller_path = caller_path
        self._headless = headless
        self._browser_engine = browser_engine
        self._profile_dir = profile_dir
        self._playwright_enabled = playwright_enabled

        self._supervisor: BrowserSupervisor | None = None
        self._pw: Playwright | None = None
        self._browser = None
        # Set (in _connect / _launch_local) to the profile's persistent
        # BrowserContext when profile_dir is in use, so every task reuses
        # it instead of getting an isolated one. See new_context() and
        # reuses_shared_context below.
        self._shared_context: BrowserContext | None = None
        # (profile_dir, is_copy) pairs from prepare_profile_dir(), tracked
        # separately so each is only ever cleaned up by the process that
        # created it. _shared_profile_copy backs the one Chromium instance
        # and lives in the main process (_on_worker_init/_on_worker_shutdown);
        # _local_profile_copy backs a worker process's own Firefox and lives
        # there (_launch_local/_disconnect). Forked children inherit
        # _shared_profile_copy's value from the pre-fork parent but must
        # never act on it - only the main process owns that copy.
        self._shared_profile_copy: tuple[str, bool] | None = None
        self._local_profile_copy: tuple[str, bool] | None = None

        if playwright_enabled:
            signals.worker_process_init.connect(self._on_process_init)
            signals.worker_process_shutdown.connect(self._on_process_shutdown)
            if self._browser_engine == "chromium":
                signals.worker_init.connect(self._on_worker_init)
                signals.worker_shutdown.connect(self._on_worker_shutdown)

        # After the definition of self.features and self.celery, we build the default features.
        build_default_libretti(self)

    @property
    def redis(self) -> Redis:
        # Created lazily so no socket exists in this process before the
        # worker pool forks: a connection opened pre-fork would be shared
        # (and corrupted) across every forked child.
        if self._redis is None:
            self._redis = Redis(host=self._redis_host, port=self._redis_port)
        return self._redis

    @property
    def libretti(self):
        return self._libretti

    @property
    def playwright_enabled(self):
        return self._playwright_enabled

    @property
    def browser_engine(self) -> str:
        return self._browser_engine

    @property
    def worker_session(self):
        """
        Deprecated. Always returns ``None``.

        Pre-refactor, this returned the single ``WorkerSession`` living for
        the lifetime of the worker process. There is no such process-level
        session anymore: a fresh session is created per task and passed
        directly to the libretto function instead. Use that argument rather
        than reaching for ``app.worker_session``.
        """
        warnings.warn(
            "'ChaninaApplication.worker_session' is deprecated and always "
            "returns None: sessions are now created per task and passed as "
            "an argument to the libretto function instead of being stored "
            "on the app. This property will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        return None

    def _on_worker_init(self, **_):
        """ Main process, before the fork: start (or adopt) the shared browser. """
        profile_dir = self._profile_dir
        if profile_dir:
            profile_dir, is_copy = prepare_profile_dir(profile_dir)
            self._shared_profile_copy = (profile_dir, is_copy)

        self._supervisor = BrowserSupervisor(
            redis=self.redis,
            key=self._browser_key,
            headless=self._headless,
            profile_dir=profile_dir,
        )
        self._supervisor.ensure_alive()
        self._supervisor.start_monitor()
        logging.info("BrowserSupervisor ready.")

    def _on_worker_shutdown(self, **_):
        """ Main process: stop the shared browser subprocess. """
        if self._supervisor:
            self._supervisor.stop()
            self._supervisor = None
        if self._shared_profile_copy:
            cleanup_profile_dir(*self._shared_profile_copy)
            self._shared_profile_copy = None
        logging.info("BrowserSupervisor stopped.")

    def _on_process_init(self, **_):
        """ Worker child, after the fork: attach to a browser, one way or another. """
        if self._browser_engine == "chromium":
            self._connect()
            logging.info("Connected to the shared browser.")
        else:
            self._launch_local()
            logging.info("Local Firefox launched for this worker.")

    def _on_process_shutdown(self, **_):
        """ Worker child: tear down this process's browser handle. """
        self._disconnect()
        logging.info("Browser handle closed for this worker.")

    def _connect(self) -> None:
        """
        Chromium engine: attach to the shared browser over CDP.

        With a profile_dir, the browser was launched (in browser_process.py)
        via launch_persistent_context, which creates exactly one
        BrowserContext backed by that profile's cookies/storage/etc. That
        context is visible here too, over CDP, as browser.contexts[0] - a
        fresh one from new_context() would be an unrelated, blank context
        that never sees the profile's state. So with a profile, every task
        reuses that same context instead (see new_context()).
        """
        endpoint = self.redis.get(self._browser_key)
        if not endpoint:
            raise ConnectionError(f"No browser CDP endpoint published under '{self._browser_key}'.")
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp(endpoint.decode())
        if self._profile_dir:
            if not self._browser.contexts:
                raise RuntimeError(
                    "profile_dir is set but the shared browser has no context yet; "
                    "expected its persistent profile context to already exist."
                )
            self._shared_context = self._browser.contexts[0]

    def _launch_local(self) -> None:
        """
        Firefox engine: launch a Firefox instance owned by this worker
        process alone.

        Without a profile_dir this is a plain launch(): the resulting
        Browser hands out one fresh, isolated BrowserContext per task via
        new_context(), same as the chromium engine.

        With a profile_dir, Playwright rejects a raw '-profile' CLI arg on
        launch() (same guard as Chromium's '--user-data-dir') and requires
        launch_persistent_context(user_data_dir=...) instead - which
        returns a BrowserContext, not a Browser, and can't spawn further
        contexts of its own. So with a profile, every task on this worker
        process shares that single persistent context instead of getting
        an isolated one (see new_context() / reuses_shared_context).

        The directory actually handed to Firefox is a disposable copy of
        profile_dir (see prepare_profile_dir), never profile_dir itself -
        and a given profile directory can still only be opened by one
        running Firefox at a time, so this only works cleanly with
        concurrency=1 (enforced by chanina.__main__.run_worker).
        """
        self._pw = sync_playwright().start()
        if self._profile_dir:
            profile_dir, is_copy = prepare_profile_dir(self._profile_dir)
            self._local_profile_copy = (profile_dir, is_copy)
            self._browser = self._pw.firefox.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=self._headless,
            )
            # Here the persistent context IS the launched handle itself.
            self._shared_context = self._browser
        else:
            self._browser = self._pw.firefox.launch(headless=self._headless)
            self._shared_context = None

    def _disconnect(self) -> None:
        # For chromium this disconnects without closing the remote browser
        # (its persistent profile context, if any, keeps living there for
        # the next worker to reconnect to); for firefox this owns and
        # actually closes the local browser (context included).
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception as e:
                logging.error(f"Closed the browser handle with an exception: {e}")
            self._browser = None
        self._shared_context = None
        if self._local_profile_copy:
            cleanup_profile_dir(*self._local_profile_copy)
            self._local_profile_copy = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None

    def _reconnect(self, retries: int = 5, delay: float = 2.0) -> None:
        """
        Called from a worker child when the browser handle is found dead
        (e.g. the browser crashed mid-task). For chromium, retries against
        Redis to give the main process's BrowserSupervisor monitor time to
        restart the browser and republish its endpoint. For firefox, just
        relaunches a fresh local instance.
        """
        self._disconnect()
        attach = self._connect if self._browser_engine == "chromium" else self._launch_local
        last_error: Exception | None = None
        for _ in range(retries):
            try:
                attach()
                return
            except Exception as e:
                last_error = e
                time.sleep(delay)
        raise ConnectionError("Could not reconnect to the browser.") from last_error

    @property
    def reuses_shared_context(self) -> bool:
        """
        True when new_context() hands back the same BrowserContext on
        every call instead of a fresh, isolated one (currently: whenever
        profile_dir is set, for either engine - a fresh context wouldn't
        see the profile's cookies/storage). Libretto uses this to know
        whether it owns the context it got and should close it once the
        task returns.
        """
        return self._shared_context is not None

    def _acquire_context(self, **kwargs) -> BrowserContext:
        if self._shared_context is not None:
            return self._shared_context
        return self._browser.new_context(**kwargs)

    def new_context(self, **kwargs) -> BrowserContext:
        """
        Get a BrowserContext for a task to use.

        Normally this creates a fresh, isolated context (meant to be used
        by one task and closed afterwards). The one exception is when a
        profile_dir is set: see reuses_shared_context.
        """
        if not self._playwright_enabled:
            raise RuntimeError("Playwright is disabled for this application.")
        try:
            return self._acquire_context(**kwargs)
        except Exception:
            logging.warning("Browser connection lost, attempting to reconnect ...")
            self._reconnect()
            return self._acquire_context(**kwargs)

    def libretto(self, title: str, **kwargs) -> Callable:
        """
        Decorator for feature to be added to the main
        loop.
        The new feature is registered in a dict with the given identifier
        as the "command name" that will trigger the feature.
        """
        def decorator(func: Callable) -> Callable:
            libretto = Libretto(
                app=self,
                func=func,
                title=title,
                **kwargs
            )
            self.libretti[title] = libretto
            return func
        return decorator
