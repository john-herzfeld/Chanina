import logging
from argparse import ArgumentParser

from chanina.core.chanina import ChaninaApplication
from chanina.utils import import_from_string, ImportFromStringError


def import_application_object(path: str) -> ChaninaApplication:
    """ Import the ChaninaApplication instance at 'module.module:attribute'. """
    try:
        chanina_app = import_from_string(path)
    except ImportFromStringError as e:
        logging.error(f"The specified app path is incorrect: {e}")
        raise e

    if not isinstance(chanina_app, ChaninaApplication):
        raise TypeError(
            f"{chanina_app} is not a valid ChaninaApplication object. ({type(chanina_app)})"
        )
    return chanina_app


def import_config(config: list[str]):
    """
    Parse the list of nargs passed to the cli and makes it a dict of args.
    nargs needs to be passed in the format: -r key=value key2=value2.
    Exceptions are raised if anything is not correct.
    """
    conf = {}
    if not config:
        return conf

    for kv in config:
        if not "=" in kv:
            continue
        k, v = kv.split("=", 1)
        if not k or not v:
            raise ValueError(f"Arguments passed for flag '-r' but could not be turned into a valid dict. ({kv})")
        conf[k] = v

    if not conf:
        raise KeyError("Arguments passed for flag '-r' got parsed into an empty dictionary.")

    return conf


def add_arguments(argparser: ArgumentParser) -> None:
    """ Register the chanina CLI's arguments on argparser. """
    group = argparser.add_mutually_exclusive_group(required=False)
    argparser.add_argument(
        "--app",
        "-a",
        help="Path of the ChaninaApplication's instance. (format: 'module.module:app')",
        required=True,
        type=str
    )
    group.add_argument(
        "--libretto",
        "-l",
        help="Only runs the libretto specified here. (identifier only)",
        required=False,
        default="chanina.list_libretti",
        type=str
    )
    group.add_argument(
        "--celery",
        "-c",
        help="Runs the celery app, every var=value after this flag will be passed to celery.",
        required=False,
        nargs="*"
    )
    argparser.add_argument(
        "--config",
        "-g",
        help="Only in -t mode. A config to pass to the task.",
        nargs="*"
    )


def run_worker(app: ChaninaApplication, command: str = "worker", **options) -> None:
    """
    Start the Celery worker, forwarding every k=v CLI argument as --k=v
    (or bare --k when v is a truthy bool).

    A given Firefox profile directory can only be opened by one running
    Firefox at a time, and browser_engine="firefox" gives every worker
    process its own local Firefox (see ChaninaApplication's docstring), so
    concurrency is forced to 1 for that engine regardless of what was
    passed in.
    """
    if command == "worker" and app.browser_engine == "firefox":
        requested = options.get("concurrency")
        if requested not in (None, "1", 1):
            logging.warning(
                f"browser_engine='firefox' only supports one worker process "
                f"at a time; overriding concurrency={requested!r} with concurrency=1."
            )
        options["concurrency"] = 1

    argv = [command]

    for k, v in options.items():
        k = k.replace("_", "-")
        if isinstance(v, bool):
            if v:
                argv.append(f"--{k}")
        else:
            argv.append(f"--{k}={v}")

    app.celery.start(argv)


def run() -> None:
    """ Entry point for `python -m chanina`. """
    argparser = ArgumentParser()
    add_arguments(argparser)
    args = argparser.parse_args()

    app_path = args.app
    app = import_application_object(app_path)

    celery_args = args.celery
    title = args.libretto
    config_as_list = args.config

    # First we check if the command is for a celery worker.
    if isinstance(celery_args, list):
        args = import_config(celery_args)
        run_worker(app, **args)
    else:
        # Transform config into the needed components for the run.
        config = import_config(config_as_list)
        app.libretti[title].task.s(**config).apply_async()

if __name__ == "__main__":
    run()
