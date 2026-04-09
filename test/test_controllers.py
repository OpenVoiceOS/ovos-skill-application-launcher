"""Cross-platform controller tests for ovos-skill-application-launcher.

These tests run on any platform — all OS-specific calls (subprocess,
filesystem, shutil.which) are mocked. They cover:

* the get_controller() factory dispatch table
* a smoke pass for each controller's launch / close / is_running paths
* the abstract base class contract
* the Windows stub raising NotImplementedError
"""

from unittest.mock import MagicMock, patch

import pytest

import sys
import os

# Make the in-tree controllers/ subdirectory importable as a top-level
# package for the tests, mirroring how setup.py installs it.
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from controllers import ApplicationController, get_controller  # noqa: E402
from controllers.base import ApplicationController as BaseController  # noqa: E402
from controllers.linux import LinuxApplicationController  # noqa: E402
from controllers.macos import MacOSApplicationController  # noqa: E402


# ---- factory dispatch ----------------------------------------------------


@pytest.mark.parametrize(
    "platform,expected_cls",
    [
        ("linux", LinuxApplicationController),
        ("linux2", LinuxApplicationController),
        ("darwin", MacOSApplicationController),
        ("macos", MacOSApplicationController),
    ],
)
def test_get_controller_dispatches_by_platform(platform, expected_cls):
    """Verify the factory routes to the right controller."""
    # Linux and Mac controllers do filesystem work in __init__, so we need
    # to neutralize that.
    if expected_cls is LinuxApplicationController:
        with patch("controllers.linux.which", return_value=None):
            ctrl = get_controller(settings={"controller_override": platform})
    else:
        with patch("controllers.macos.which", return_value=None), \
             patch.object(
                 MacOSApplicationController, "_build_app_aliases", return_value={}
             ):
            ctrl = get_controller(settings={"controller_override": platform})

    assert isinstance(ctrl, expected_cls)


def test_get_controller_unknown_platform_falls_back_to_linux():
    with patch("controllers.linux.which", return_value=None):
        ctrl = get_controller(settings={"controller_override": "haiku"})
    assert isinstance(ctrl, LinuxApplicationController)


def test_get_controller_threads_native_langs_into_settings():
    """native_langs should be merged into the controller's extra_langs setting."""
    with patch("controllers.linux.which", return_value=None):
        ctrl = get_controller(settings={"thresh": 0.5}, native_langs=["en-US", "fr-FR"])
    assert ctrl.settings["extra_langs"] == ["en-US", "fr-FR"]
    assert ctrl.settings["thresh"] == 0.5


def test_get_controller_windows_raises():
    from controllers.windows import WindowsApplicationController  # noqa: F401

    with pytest.raises(NotImplementedError):
        get_controller(settings={"controller_override": "win32"})


# ---- abstract base contract ----------------------------------------------


def test_base_class_is_abstract():
    with pytest.raises(TypeError):
        BaseController()  # type: ignore[abstract]


def test_application_controller_is_base_alias():
    """The package re-exports the base class for type hints."""
    assert ApplicationController is BaseController


def test_base_default_methods_are_safe_noops():
    """can_switch_windows / switch_to_app / match_process have safe defaults."""

    class _Minimal(BaseController):
        @property
        def app_aliases(self):
            return {}

        def launch_app(self, app):
            return False

        def close_app(self, app):
            return False

        def is_running(self, app):
            return False

    c = _Minimal()
    assert c.can_switch_windows() is False
    assert c.switch_to_app("anything") is False
    assert list(c.match_process("anything")) == []
    # refresh_app_cache is a no-op but should not raise
    c.refresh_app_cache()


# ---- Linux controller smoke tests ----------------------------------------


def _make_linux(settings=None):
    """Build a LinuxApplicationController without touching the filesystem."""
    settings = settings or {}
    with patch("controllers.linux.which", return_value="/usr/bin/wmctrl"):
        ctrl = LinuxApplicationController(settings)
    # Pre-seed the cache so launch/close don't try to read /usr/share.
    ctrl._app_cache = {"Firefox": "firefox", "Calculator": "kcalc"}
    return ctrl


@patch("controllers.linux.subprocess.Popen")
def test_linux_launch_app_runs_subprocess(mock_popen):
    ctrl = _make_linux()
    assert ctrl.launch_app("firefox") is True
    mock_popen.assert_called_once()
    args, _ = mock_popen.call_args
    assert args[0] == ["firefox"]


@patch("controllers.linux.subprocess.Popen", side_effect=OSError("nope"))
def test_linux_launch_app_returns_false_on_error(_mock_popen):
    ctrl = _make_linux()
    assert ctrl.launch_app("firefox") is False


def test_linux_launch_app_no_match_returns_false():
    ctrl = _make_linux()
    ctrl.settings["thresh"] = 0.99
    assert ctrl.launch_app("totally not an app") is False


def test_linux_can_switch_windows_when_wmctrl_present():
    ctrl = _make_linux()
    assert ctrl.can_switch_windows() is True


def test_linux_can_switch_windows_disabled_via_setting():
    with patch("controllers.linux.which", return_value="/usr/bin/wmctrl"):
        ctrl = LinuxApplicationController({"disable_window_manager": True})
    assert ctrl.can_switch_windows() is False


# ---- macOS controller smoke tests ----------------------------------------


def _make_macos(settings=None):
    settings = settings or {}
    with patch("controllers.macos.which", return_value="/usr/bin/osascript"), \
         patch.object(MacOSApplicationController, "_build_app_aliases", return_value={}):
        ctrl = MacOSApplicationController(settings)
    ctrl._app_cache = {"Safari": "/Applications/Safari.app", "Calculator": "/Applications/Calculator.app"}
    ctrl._cache_build_failed = False
    return ctrl


@patch("controllers.macos.subprocess.run")
@patch("controllers.macos.subprocess.Popen")
def test_macos_launch_app_prefers_applescript_when_osascript_present(mock_popen, mock_run):
    """AppleScript activate is preferred over `open` to avoid the
    launchd RBSRequestErrorDomain Code=5 spawn error when the skill
    runs from a LaunchAgent.
    """
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    ctrl = _make_macos()
    ctrl._app_cache = {"Safari": "/Applications/Safari.app"}
    assert ctrl.launch_app("safari") is True
    # AppleScript path was used; `open` was not invoked.
    args, _ = mock_run.call_args
    assert args[0][0] == "/usr/bin/osascript"
    assert "activate" in args[0][2]
    assert 'tell application "Safari"' in args[0][2]
    mock_popen.assert_not_called()


@patch("controllers.macos.subprocess.run")
@patch("controllers.macos.subprocess.Popen")
def test_macos_launch_app_falls_back_to_open_when_applescript_fails(mock_popen, mock_run):
    """If osascript returns non-zero, fall back to `open` so we still
    launch *something*.
    """
    mock_run.return_value = MagicMock(returncode=1, stderr="execution error")
    ctrl = _make_macos()
    ctrl._app_cache = {"Safari": "/Applications/Safari.app"}
    assert ctrl.launch_app("safari") is True
    mock_popen.assert_called_once_with(["open", "/Applications/Safari.app"])


@patch("controllers.macos.subprocess.run")
@patch("controllers.macos.subprocess.Popen")
def test_macos_launch_app_open_minus_a_fallback_for_bare_name(mock_popen, mock_run):
    """When osascript fails on a bare app name, fall back to ``open -a``."""
    mock_run.return_value = MagicMock(returncode=1, stderr="execution error")
    ctrl = _make_macos()
    ctrl._app_cache = {"Safari": "Safari"}
    assert ctrl.launch_app("safari") is True
    mock_popen.assert_called_once_with(["open", "-a", "Safari"])


@patch("controllers.macos.subprocess.Popen")
def test_macos_launch_app_uses_open_when_osascript_unavailable(mock_popen):
    """Without osascript, the controller falls straight through to ``open``."""
    with patch("controllers.macos.which", return_value=None), \
         patch.object(MacOSApplicationController, "_build_app_aliases", return_value={}):
        ctrl = MacOSApplicationController()
    ctrl._app_cache = {"Safari": "/Applications/Safari.app"}
    ctrl._cache_build_failed = False
    assert ctrl.launch_app("safari") is True
    mock_popen.assert_called_once_with(["open", "/Applications/Safari.app"])


@patch("controllers.macos.subprocess.run")
def test_macos_switch_to_app_runs_applescript(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    ctrl = _make_macos()
    assert ctrl.switch_to_app("safari") is True
    args, _ = mock_run.call_args
    assert args[0][0] == "/usr/bin/osascript"
    assert args[0][1] == "-e"
    assert "activate" in args[0][2]
    assert "Safari" in args[0][2]


@patch("controllers.macos.subprocess.run")
def test_macos_close_by_applescript_runs_quit(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    ctrl = _make_macos()
    assert ctrl.close_by_applescript("safari") is True
    args, _ = mock_run.call_args
    assert "quit" in args[0][2]


def test_macos_can_switch_windows_when_osascript_present():
    ctrl = _make_macos()
    assert ctrl.can_switch_windows() is True


def test_macos_can_switch_windows_disabled_via_setting():
    with patch("controllers.macos.which", return_value="/usr/bin/osascript"), \
         patch.object(MacOSApplicationController, "_build_app_aliases", return_value={}):
        ctrl = MacOSApplicationController({"disable_window_manager": True})
    assert ctrl.can_switch_windows() is False


# ---- macOS .app bundle parser --------------------------------------------


def test_macos_parse_app_bundle_handles_missing_plist(tmp_path):
    fake_app = tmp_path / "Fake.app"
    fake_app.mkdir()
    result = MacOSApplicationController.parse_app_bundle(str(fake_app))
    assert result == {}


def test_macos_parse_app_bundle_extracts_metadata(tmp_path):
    import plistlib

    app_dir = tmp_path / "Calculator.app"
    contents = app_dir / "Contents"
    contents.mkdir(parents=True)
    plist_path = contents / "Info.plist"
    with open(plist_path, "wb") as f:
        plistlib.dump(
            {
                "CFBundleName": "Calculator",
                "CFBundleIdentifier": "com.apple.calculator",
                "CFBundleShortVersionString": "10.16",
            },
            f,
        )

    result = MacOSApplicationController.parse_app_bundle(str(app_dir))
    assert result["name"] == "Calculator"
    assert result["bundle_id"] == "com.apple.calculator"
    assert result["version"] == "10.16"
    assert result["path"] == str(app_dir)


def test_macos_parse_app_bundle_falls_back_to_directory_name(tmp_path):
    import plistlib

    app_dir = tmp_path / "MyApp.app"
    contents = app_dir / "Contents"
    contents.mkdir(parents=True)
    plist_path = contents / "Info.plist"
    # Empty plist — no CFBundleName / CFBundleDisplayName
    with open(plist_path, "wb") as f:
        plistlib.dump({}, f)

    result = MacOSApplicationController.parse_app_bundle(str(app_dir))
    assert result["name"] == "MyApp"
