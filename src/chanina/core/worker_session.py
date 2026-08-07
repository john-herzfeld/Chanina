"""
Deprecated compatibility layer for the pre-refactor ``WorkerSession`` API.

Before the shared-browser refactor, ``ChaninaApplication`` kept one
``WorkerSession`` alive per worker *process* (a Playwright driver plus a
single ``BrowserContext``), and libretto functions received that shared
session as their context argument. Since the refactor, a fresh
``BrowserContext`` is created per *task* instead (see
:mod:`chanina.core.browser_supervisor` and :meth:`Libretto._register_as_task
<chanina.core.libretti.Libretto._register_as_task>`), and that context is
what libretto functions receive.

``WorkerSession`` now wraps that per-task context so code written against
the old API keeps working unmodified: attribute access not defined here
transparently falls through to the wrapped ``BrowserContext`` (so
``session.new_page()``, ``session.cookies()``, etc. behave exactly like
before), while the handful of members that only existed on the old
process-level session (``user_context``, ``playwright``, dict-style
``new_page(args)``) raise a ``DeprecationWarning`` on use.

New code should just use the context argument directly and drop any of the
attributes flagged below as deprecated.
"""
import logging
import warnings
from typing import Any

from playwright.sync_api import BrowserContext, Page, Playwright


class WorkerSession:
    """
    Backward-compatible wrapper around a per-task ``BrowserContext``.

    Instances are created internally by :class:`chanina.core.libretti.Libretto`
    for every task invocation; user code should not need to construct this
    class directly.
    """

    def __init__(self, browser_context: BrowserContext, app) -> None:
        self.browser_context = browser_context
        self.app = app
        # Pre-refactor, this dict lived for the lifetime of the worker
        # process and was shared across every task it handled. It is now
        # scoped to a single task, since contexts are created per task.
        self.user_context: dict[str, Any] = {}
        # Pages opened through this session, tracked so Libretto can close
        # any the task left open once it returns (or raises) - see
        # _close_opened_pages. Only pages opened via this session's
        # new_page() are tracked; a page opened directly on the underlying
        # BrowserContext (or a popup opened by page content itself) is not.
        self._opened_pages: list[Page] = []

    @property
    def playwright(self) -> Playwright:
        """
        Deprecated. Returns the app's internal Playwright driver handle.

        This used to be the session's own dedicated driver instance; it is
        now the single driver shared by every task in the worker process,
        so mutating it from task code is unsafe and unsupported.
        """
        warnings.warn(
            "WorkerSession.playwright is deprecated and now returns the "
            "worker process's shared Playwright driver instead of a "
            "session-private one. It will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.app._pw

    def new_page(self, args: dict | None = None, **kwargs) -> Page:
        """
        Create a new page on the wrapped context.

        The legacy signature took a single positional ``dict`` of Playwright
        kwargs (``session.new_page({"viewport": ...})``); the modern
        ``BrowserContext.new_page`` takes real keyword arguments instead.
        Both styles are accepted here, but the positional-dict form is
        deprecated.
        """
        if args:
            warnings.warn(
                "WorkerSession.new_page(args={...}) is deprecated, pass "
                "keyword arguments directly instead: new_page(**kwargs).",
                DeprecationWarning,
                stacklevel=2,
            )
            kwargs = {**args, **kwargs}
        page = self.browser_context.new_page(**kwargs)
        self._opened_pages.append(page)
        return page

    def _close_opened_pages(self) -> None:
        """
        Close every still-open page this session opened via new_page().

        Called by Libretto once the task returns or raises, so a page a
        failing task left open (e.g. mid-navigation, before its own
        cleanup code ran) doesn't linger forever. This matters most when
        ``app.reuses_shared_context`` is set: the context itself outlives
        the task and is never closed, so nothing else would ever close
        pages left open on it.
        """
        for page in self._opened_pages:
            try:
                if not page.is_closed():
                    page.close()
            except Exception as e:
                logging.warning(f"Failed to close a page left open by a task: {e}")
        self._opened_pages.clear()

    def close(self) -> None:
        """
        Deprecated. Closes the wrapped context.

        Libretto already closes the task's context automatically once the
        task returns, so calling this explicitly is no longer necessary.
        It remains safe to call (idempotent) for old code that still does.
        """
        warnings.warn(
            "WorkerSession.close() is deprecated: the task context is now "
            "closed automatically by Libretto after the task returns.",
            DeprecationWarning,
            stacklevel=2,
        )
        try:
            self.browser_context.close()
        except Exception:
            pass

    def __getattr__(self, name: str):
        # Only reached for attributes not found on the instance/class
        # itself, i.e. anything that isn't one of the members defined
        # above. Transparently proxies to the wrapped BrowserContext so
        # this object can stand in for a raw context too.
        return getattr(self.browser_context, name)
