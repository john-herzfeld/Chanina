from unittest.mock import MagicMock

import pytest

from chanina.__main__ import import_config, run_worker


def test_import_config_returns_empty_dict_for_no_config():
    assert import_config(None) == {}
    assert import_config([]) == {}


def test_import_config_parses_key_value_pairs():
    assert import_config(["a=1", "b=2"]) == {"a": "1", "b": "2"}


def test_import_config_splits_only_on_the_first_equals():
    assert import_config(["token=abc=def"]) == {"token": "abc=def"}


def test_import_config_skips_entries_without_an_equals_sign():
    assert import_config(["a=1", "not-a-kv"]) == {"a": "1"}


def test_import_config_raises_on_a_key_or_value_missing():
    with pytest.raises(ValueError):
        import_config(["=1"])
    with pytest.raises(ValueError):
        import_config(["a="])


def test_import_config_raises_when_everything_gets_skipped():
    with pytest.raises(KeyError):
        import_config(["not-a-kv"])


def test_import_config_bare_as_flag_turns_bare_tokens_into_true():
    assert import_config(["without-mingle"], bare_as_flag=True) == {"without-mingle": True}


def test_import_config_bare_as_flag_mixes_with_key_value_pairs():
    assert import_config(
        ["without-mingle", "concurrency=4", "without-gossip"], bare_as_flag=True
    ) == {"without-mingle": True, "concurrency": "4", "without-gossip": True}


def test_import_config_bare_as_flag_still_raises_on_a_key_or_value_missing():
    with pytest.raises(ValueError):
        import_config(["a="], bare_as_flag=True)


def _make_fake_app(browser_engine: str) -> MagicMock:
    app = MagicMock()
    app.browser_engine = browser_engine
    return app


def test_run_worker_forces_concurrency_1_for_firefox_when_unset():
    app = _make_fake_app("firefox")

    run_worker(app)

    app.celery.start.assert_called_once_with(["worker", "--concurrency=1"])


def test_run_worker_overrides_a_higher_requested_concurrency_for_firefox():
    app = _make_fake_app("firefox")

    run_worker(app, concurrency=4)

    app.celery.start.assert_called_once_with(["worker", "--concurrency=1"])


def test_run_worker_leaves_concurrency_alone_for_chromium():
    app = _make_fake_app("chromium")

    run_worker(app, concurrency=4)

    app.celery.start.assert_called_once_with(["worker", "--concurrency=4"])


def test_run_worker_does_not_force_concurrency_for_non_worker_commands():
    app = _make_fake_app("firefox")

    run_worker(app, command="inspect")

    app.celery.start.assert_called_once_with(["inspect"])


def test_run_worker_forwards_bare_boolean_flags_from_import_config():
    app = _make_fake_app("chromium")
    options = import_config(["without-mingle", "without-gossip", "concurrency=4"], bare_as_flag=True)

    run_worker(app, **options)

    app.celery.start.assert_called_once_with(
        ["worker", "--without-mingle", "--without-gossip", "--concurrency=4"]
    )
