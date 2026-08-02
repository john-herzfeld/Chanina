import pytest

from chanina.__main__ import import_config


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
