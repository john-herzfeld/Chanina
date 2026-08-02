import pytest

from chanina.core.chanina import ChaninaApplication


def _make_app(**kwargs) -> ChaninaApplication:
    # playwright_enabled=False keeps construction light: no signal handlers
    # are registered, and nothing tries to talk to Redis or a browser.
    return ChaninaApplication(__file__, playwright_enabled=False, **kwargs)


def test_browser_engine_defaults_to_chromium():
    app = _make_app()
    assert app._browser_engine == "chromium"


def test_browser_engine_rejects_unknown_values():
    with pytest.raises(ValueError):
        _make_app(browser_engine="webkit")


@pytest.mark.parametrize(
    "browser_name,expected_engine",
    [("firefox", "firefox"), ("chrome", "chromium")],
)
def test_legacy_browser_name_maps_onto_browser_engine(browser_name, expected_engine):
    with pytest.warns(DeprecationWarning):
        app = _make_app(browser_name=browser_name)

    assert app._browser_engine == expected_engine


def test_legacy_browser_name_rejects_unknown_values_like_before():
    with pytest.warns(DeprecationWarning):
        with pytest.raises(ValueError):
            _make_app(browser_name="edge")


def test_explicit_browser_engine_takes_precedence_over_legacy_browser_name():
    with pytest.warns(DeprecationWarning):
        app = _make_app(browser_name="chrome", browser_engine="firefox")

    assert app._browser_engine == "firefox"


def test_legacy_user_profile_path_aliases_onto_profile_dir():
    with pytest.warns(DeprecationWarning):
        app = _make_app(user_profile_path="/some/profile")

    assert app._profile_dir == "/some/profile"


def test_explicit_profile_dir_takes_precedence_over_legacy_user_profile_path():
    with pytest.warns(DeprecationWarning):
        app = _make_app(user_profile_path="/legacy/profile", profile_dir="/new/profile")

    assert app._profile_dir == "/new/profile"


def test_profile_dir_defaults_to_none():
    app = _make_app()
    assert app._profile_dir is None


def test_worker_session_property_is_deprecated_and_returns_none():
    app = _make_app()

    with pytest.warns(DeprecationWarning):
        assert app.worker_session is None
