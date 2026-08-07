import importlib
import logging
import datetime
import os
import shutil
import signal
import tempfile
from pathlib import Path

from colorama import Fore, Style
from celery import signals


def s_now() -> str:
    """ Current local time formatted as 'HH:MM:SS'. """
    return datetime.datetime.strftime(datetime.datetime.now(), "%H:%M:%S")


def prepare_profile_dir(source: str) -> tuple[str, bool]:
    """
    Get a browser profile directory safe for one browser to own exclusively,
    given a user-supplied `source` path.

    A running browser writes lock files, session data, and caches into
    whatever directory it's pointed at, and a given profile can only be
    opened by one running browser at a time. So `source` is treated as a
    read-only template rather than handed to the browser directly: if it
    already holds a profile, it's copied into a fresh disposable directory
    under the system temp dir and that copy's path is returned (with
    `is_copy=True`), leaving `source` untouched for the next launch to
    copy from again. If `source` doesn't exist yet, there's nothing to
    protect, so it's created and used as-is (`is_copy=False`) - it becomes
    the template later launches will copy.

    Returns (profile_dir, is_copy); pass both to cleanup_profile_dir once
    the browser using it is done.
    """
    src = Path(source).resolve()
    if not src.exists():
        src.mkdir(parents=True)
        return str(src), False
    if not src.is_dir():
        raise ValueError(f"{src} is not a valid directory.")

    dest = Path(tempfile.mkdtemp(prefix="chanina-profile-"))
    dest.rmdir()  # copytree refuses to copy into a directory that already exists.
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("*.lock", "lock", "Singleton*"))
    return str(dest), True


def cleanup_profile_dir(profile_dir: str, is_copy: bool) -> None:
    """ Remove a disposable profile directory previously returned by prepare_profile_dir. """
    if not is_copy:
        return
    logging.info(f"Deleting temporary profile copy {profile_dir} ...")
    shutil.rmtree(profile_dir, ignore_errors=True)


def crash_process(reason: str, pid: int | None = None) -> None:
    """
    Kill a process immediately with SIGKILL, after logging why.

    Used when the browser (shared Chromium subprocess or a worker's own
    local Firefox) becomes unrecoverable: a graceful shutdown could hang
    forever waiting on work that will never finish without a browser, so
    this favors an immediate, unmistakable death instead - the kind an
    external supervisor (e.g. Kubernetes' restartPolicy) reacts to by
    relaunching the whole worker from scratch.
    """
    target = os.getpid() if pid is None else pid
    logging.critical(f"Fatal: {reason}. Killing process {target} so it gets relaunched.")
    os.kill(target, signal.SIGKILL)


class ImportFromStringError(Exception):
    """ Raised by import_from_string when the target can't be imported. """


def import_from_string(import_str: str):
    """
    Import an object from a 'module.submodule:attribute' string, e.g. how
    uvicorn.importer.import_from_string works, without depending on uvicorn
    for a single helper function.
    """
    module_str, _, attr_str = import_str.partition(":")
    if not module_str or not attr_str:
        raise ImportFromStringError(
            f"Import string '{import_str}' must be in format '<module>:<attribute>'."
        )

    try:
        module = importlib.import_module(module_str)
    except ImportError as e:
        raise ImportFromStringError(f"Could not import module '{module_str}': {e}") from e

    instance = module
    try:
        for attr in attr_str.split("."):
            instance = getattr(instance, attr)
    except AttributeError as e:
        raise ImportFromStringError(f"Attribute '{attr_str}' not found in module '{module_str}': {e}") from e

    return instance


class ColorFormatter(logging.Formatter):
    """ Logging formatter that colors the level name and message by severity. """

    COLORS = {
        "DEBUG": Fore.LIGHTWHITE_EX,
        "INFO": Fore.CYAN,
        "WARNING": Fore.YELLOW,
        "ERROR": Fore.RED,
        "CRITICAL": "\033[41m"
    }
    RESET = Style.RESET_ALL

    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        formatted = super().format(record)
        return f"{color}{formatted}{self.RESET}"


@signals.after_setup_logger.connect
def setup_logging(logger, *_, **__):
    """ Celery hook: apply ColorFormatter to every handler of its logger. """
    for handler in logger.handlers:
        handler.setFormatter(
            ColorFormatter(
                "[%(asctime)s %(levelname)-8s] [%(module)s] %(message)s",
                "%m-%d-%Y %H:%M:%S"
            )
        )

    logger.setLevel(logging.INFO)
