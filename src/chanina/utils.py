import importlib
import logging
import datetime

from colorama import Fore, Style
from celery import signals


def s_now() -> str:
    """ Current local time formatted as 'HH:MM:SS'. """
    return datetime.datetime.strftime(datetime.datetime.now(), "%H:%M:%S")


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
