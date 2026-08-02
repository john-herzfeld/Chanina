"""
Standalone entry point launched as a subprocess by BrowserSupervisor.

This script owns the actual Chromium process and the Playwright driver that
talks to it. It must never be imported into the Celery main process: keeping
the live Playwright/asyncio state out of that process is what protects the
forked worker children from inheriting a corrupted event loop / file
descriptors.

Playwright's Python bindings have no launch_server()/connect() pair (that is
Node.js only), so sharing the browser across processes is done over CDP
instead: Chromium is launched with --remote-debugging-port, and workers
attach via chromium.connect_over_cdp().

Usage: browser_process.py <"1"|"0" headless> [profile_dir]
Always invoked by BrowserSupervisor.start(); not meant to be run by hand.
"""
import signal
import socket
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

_shutdown = False


def _handle_sigterm(signum, frame) -> None:
    global _shutdown
    _shutdown = True


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _launch(pw, headless: bool, port: int, profile_dir: str | None):
    """
    Launch the shared browser, with or without a persistent profile.

    Without a profile_dir this is a plain chromium.launch(): the returned
    handle is a Browser. Chromium rejects a raw '--user-data-dir' argument
    on launch() (it requires launch_persistent_context for that), so with a
    profile_dir the handle is instead the persistent BrowserContext backed
    by that directory. Either way '--remote-debugging-port' still exposes
    the full CDP protocol, so worker children can connect_over_cdp() and
    create their own additional, isolated per-task contexts via
    new_context() exactly as before: the profile only backs the one
    default context that owns it.
    """
    args = [f"--remote-debugging-port={port}"]
    if profile_dir:
        return pw.chromium.launch_persistent_context(user_data_dir=profile_dir, headless=headless, args=args)
    return pw.chromium.launch(headless=headless, args=args)


def main() -> None:
    headless = sys.argv[1] == "1" if len(sys.argv) > 1 else True
    profile_dir = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
    if profile_dir:
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    port = _free_port()
    pw = sync_playwright().start()
    handle = _launch(pw, headless, port, profile_dir)
    # launch_persistent_context returns the profile's BrowserContext rather
    # than a Browser; it exposes the underlying Browser via .browser.
    browser = handle.browser if profile_dir else handle

    # The supervisor reads this line to get the CDP endpoint to publish.
    print(f"http://127.0.0.1:{port}", flush=True)

    try:
        while not _shutdown and browser.is_connected():
            time.sleep(1)
    finally:
        try:
            handle.close()
        except Exception:
            pass
        pw.stop()


if __name__ == "__main__":
    main()
