import pytest

from chanina.utils import ImportFromStringError, import_from_string


def test_import_from_string_returns_the_target_attribute():
    result = import_from_string("chanina.utils:s_now")
    from chanina.utils import s_now
    assert result is s_now


def test_import_from_string_supports_nested_attributes():
    result = import_from_string("chanina.utils:ColorFormatter.RESET")
    from chanina.utils import ColorFormatter
    assert result == ColorFormatter.RESET


def test_import_from_string_requires_a_colon():
    with pytest.raises(ImportFromStringError):
        import_from_string("chanina.utils")


def test_import_from_string_rejects_a_missing_module():
    with pytest.raises(ImportFromStringError):
        import_from_string("chanina.does_not_exist:s_now")


def test_import_from_string_rejects_a_missing_attribute():
    with pytest.raises(ImportFromStringError):
        import_from_string("chanina.utils:does_not_exist")
