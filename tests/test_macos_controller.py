#!/usr/bin/env python3
"""
Test suite for MacOSApplicationController

This demonstrates how the refactored macOS application management logic
can be tested independently of the voice assistant functionality.
"""

import os
import plistlib
import tempfile
import unittest
from unittest.mock import Mock, patch

# Import the controller class
from skill_mac_application_launcher.macos_controller import MacOSApplicationController


class TestMacOSApplicationController(unittest.TestCase):
    """Test cases for MacOSApplicationController."""

    def setUp(self):
        """Set up test fixtures."""
        self.settings = {
            "thresh": 0.85,
            "aliases": {
                "Calculator": ["calculator", "calc"],
                "Safari": ["browser", "web browser"],
            },
            "user_commands": {"Custom App": "/Applications/CustomApp.app"},
            "blocklist": ["Blocked App"],
            "extra_langs": ["en-US"],
            "disable_window_manager": False,
            "terminate_all": False,
        }
        self.controller = MacOSApplicationController(self.settings)

    def test_initialization(self):
        """Test controller initialization."""
        self.assertEqual(self.controller.settings, self.settings)
        self.assertIsNotNone(self.controller.osascript)

    def test_initialization_no_settings(self):
        """Test controller initialization with no settings."""
        controller = MacOSApplicationController()
        self.assertEqual(controller.settings, {})

    def test_app_aliases_caching(self):
        """Test that app aliases are cached properly."""
        # Create a fresh controller to avoid initialization cache building
        with patch(
            "skill_mac_application_launcher.macos_controller.MacOSApplicationController._build_app_aliases",
            return_value={"Test": "/test"},
        ) as mock_build:
            controller = MacOSApplicationController(self.settings)

            # First access should use the cache built during initialization
            aliases1 = controller.app_aliases
            self.assertEqual(aliases1, {"Test": "/test"})
            # Should be called once during initialization
            self.assertEqual(mock_build.call_count, 1)

            # Second access should use cache
            aliases2 = controller.app_aliases
            self.assertEqual(aliases2, {"Test": "/test"})
            self.assertEqual(mock_build.call_count, 1)  # Still only called once

            # Refresh should rebuild
            controller.refresh_app_cache()
            controller.app_aliases
            self.assertEqual(mock_build.call_count, 2)

    @patch("subprocess.Popen")
    def test_launch_app_success(self, mock_popen):
        """Test successful app launching."""
        # Mock the app aliases by setting the cache directly
        self.controller._app_cache = {"Safari": "/Applications/Safari.app"}
        result = self.controller.launch_app("Safari")
        self.assertTrue(result)
        mock_popen.assert_called_once_with(["open", "/Applications/Safari.app"])

    @patch("subprocess.Popen")
    def test_launch_app_by_name(self, mock_popen):
        """Test launching app by name (not full path)."""
        self.controller._app_cache = {"Calculator": "Calculator"}
        result = self.controller.launch_app("Calculator")
        self.assertTrue(result)
        mock_popen.assert_called_once_with(["open", "-a", "Calculator"])

    def test_launch_app_no_match(self):
        """Test launching app with no match."""
        self.controller._app_cache = {}
        result = self.controller.launch_app("NonexistentApp")
        self.assertFalse(result)

    @patch("subprocess.Popen", side_effect=Exception("Launch failed"))
    def test_launch_app_exception(self, mock_popen):
        """Test app launching with exception."""
        self.controller._app_cache = {"Safari": "/Applications/Safari.app"}
        result = self.controller.launch_app("Safari")
        self.assertFalse(result)

    def test_is_running_true(self):
        """Test is_running when app is running."""
        with patch.object(self.controller, "match_process", return_value=[Mock()]):
            result = self.controller.is_running("Safari")
            self.assertTrue(result)

    def test_is_running_false(self):
        """Test is_running when app is not running."""
        with patch.object(self.controller, "match_process", return_value=[]):
            result = self.controller.is_running("Safari")
            self.assertFalse(result)

    @patch("subprocess.run")
    def test_switch_to_app_success(self, mock_run):
        """Test successful app switching."""
        mock_run.return_value.returncode = 0
        self.controller._app_cache = {"Safari": "/Applications/Safari.app"}
        result = self.controller.switch_to_app("Safari")
        self.assertTrue(result)
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_switch_to_app_failure(self, mock_run):
        """Test failed app switching."""
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "Error"
        self.controller._app_cache = {"Safari": "/Applications/Safari.app"}
        result = self.controller.switch_to_app("Safari")
        self.assertFalse(result)

    def test_switch_to_app_no_osascript(self):
        """Test app switching when osascript is not available."""
        self.controller.osascript = None
        result = self.controller.switch_to_app("Safari")
        self.assertFalse(result)

    @patch("subprocess.run")
    def test_close_by_applescript_success(self, mock_run):
        """Test successful app closing via AppleScript."""
        mock_run.return_value.returncode = 0
        self.controller._app_cache = {"Safari": "/Applications/Safari.app"}
        result = self.controller.close_by_applescript("Safari")
        self.assertTrue(result)

    def test_close_app_applescript_then_process(self):
        """Test close_app trying AppleScript first, then process termination."""
        with patch.object(self.controller, "close_by_applescript", return_value=False) as mock_applescript:
            with patch.object(self.controller, "close_by_process", return_value=True) as mock_process:
                result = self.controller.close_app("Safari")
                self.assertTrue(result)
                mock_applescript.assert_called_once_with("Safari")
                mock_process.assert_called_once_with("Safari")

    def test_close_app_applescript_success(self):
        """Test close_app succeeding with AppleScript."""
        with patch.object(self.controller, "close_by_applescript", return_value=True) as mock_applescript:
            with patch.object(self.controller, "close_by_process") as mock_process:
                result = self.controller.close_app("Safari")
                self.assertTrue(result)
                mock_applescript.assert_called_once_with("Safari")
                mock_process.assert_not_called()

    @patch("psutil.process_iter")
    def test_match_process(self, mock_process_iter):
        """Test process matching."""
        # Create mock processes
        mock_proc1 = Mock()
        mock_proc1.info = {"pid": 123, "name": "Safari", "create_time": 1000}
        mock_proc1.status.return_value = "running"

        mock_proc2 = Mock()
        mock_proc2.info = {"pid": 124, "name": "Chrome", "create_time": 2000}
        mock_proc2.status.return_value = "running"

        mock_process_iter.return_value = [mock_proc1, mock_proc2]

        self.controller._app_cache = {"Safari": "/Applications/Safari.app"}
        with patch("ovos_utils.parse.fuzzy_match", side_effect=[0.9, 0.1, 0.1, 0.1]):
            processes = list(self.controller.match_process("Safari"))
            self.assertEqual(len(processes), 1)
            self.assertEqual(processes[0], mock_proc1)

    def test_parse_app_bundle_success(self):
        """Test successful app bundle parsing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a mock .app bundle structure
            app_path = os.path.join(temp_dir, "TestApp.app")
            contents_path = os.path.join(app_path, "Contents")
            os.makedirs(contents_path)

            # Create Info.plist
            plist_data = {
                "CFBundleName": "Test Application",
                "CFBundleDisplayName": "Test App",
                "CFBundleIdentifier": "com.test.app",
                "CFBundleShortVersionString": "1.0.0",
            }

            plist_path = os.path.join(contents_path, "Info.plist")
            with open(plist_path, "wb") as f:
                plistlib.dump(plist_data, f)

            result = MacOSApplicationController.parse_app_bundle(app_path)

            self.assertEqual(result["name"], "Test Application")
            self.assertEqual(result["path"], app_path)
            self.assertEqual(result["bundle_id"], "com.test.app")
            self.assertEqual(result["version"], "1.0.0")
            self.assertIn("Test App", result["localized_names"])

    def test_parse_app_bundle_no_plist(self):
        """Test app bundle parsing when Info.plist doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            app_path = os.path.join(temp_dir, "TestApp.app")
            os.makedirs(app_path)

            result = MacOSApplicationController.parse_app_bundle(app_path)
            self.assertEqual(result, {})

    def test_parse_app_bundle_malformed_plist(self):
        """Test app bundle parsing with malformed plist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            app_path = os.path.join(temp_dir, "TestApp.app")
            contents_path = os.path.join(app_path, "Contents")
            os.makedirs(contents_path)

            # Create malformed plist
            plist_path = os.path.join(contents_path, "Info.plist")
            with open(plist_path, "w") as f:
                f.write("invalid plist content")

            result = MacOSApplicationController.parse_app_bundle(app_path)

            self.assertEqual(result["name"], "TestApp")
            self.assertEqual(result["path"], app_path)
            self.assertEqual(result["bundle_id"], "")

    @patch("os.listdir")
    @patch("os.path.isdir")
    def test_get_macos_apps(self, mock_isdir, mock_listdir):
        """Test macOS app discovery."""
        # Mock directory structure
        mock_isdir.side_effect = lambda path: path in ["/Applications", "/Applications/Safari.app"]
        mock_listdir.return_value = ["Safari.app", "NotAnApp.txt"]

        with patch.object(MacOSApplicationController, "parse_app_bundle") as mock_parse:
            mock_parse.return_value = {
                "name": "Safari",
                "path": "/Applications/Safari.app",
                "bundle_id": "com.apple.Safari",
                "version": "1.0",
                "localized_names": [],
            }

            apps = list(MacOSApplicationController.get_macos_apps(blocklist=[]))
            self.assertEqual(len(apps), 1)
            self.assertEqual(apps[0]["name"], "Safari")

    def test_build_app_aliases(self):
        """Test building app aliases from discovered apps."""
        mock_apps = [
            {"name": "Safari", "path": "/Applications/Safari.app", "localized_names": ["Web Browser"]},
            {"name": "Calculator", "path": "/Applications/Calculator.app", "localized_names": []},
        ]

        with patch.object(self.controller, "get_macos_apps", return_value=mock_apps):
            aliases = self.controller._build_app_aliases()

            # Check main app names
            self.assertIn("Safari", aliases)
            self.assertIn("Calculator", aliases)

            # Check localized names
            self.assertIn("Web Browser", aliases)

            # Check aliases from settings
            self.assertIn("browser", aliases)  # From settings["aliases"]["Safari"]
            self.assertIn("calc", aliases)  # From settings["aliases"]["Calculator"]

            # Check user commands
            self.assertIn("Custom App", aliases)


class TestIntegration(unittest.TestCase):
    """Integration tests to verify the controller works with real macOS apps."""

    def setUp(self):
        """Set up integration test fixtures."""
        self.controller = MacOSApplicationController({"thresh": 0.85, "blocklist": [], "extra_langs": ["en-US"]})

    def test_real_app_discovery(self):
        """Test discovering real macOS applications."""
        # This test will only work on macOS systems
        try:
            apps = list(self.controller.get_macos_apps(blocklist=[]))
            self.assertGreater(len(apps), 0, "Should find at least some applications")

            # Check that common system apps are found
            app_names = [app["name"] for app in apps]
            common_apps = ["Finder", "Safari", "Calculator"]
            found_common = [app for app in common_apps if app in app_names]
            self.assertGreater(len(found_common), 0, f"Should find at least one common app from {common_apps}")

        except (OSError, PermissionError):
            self.skipTest("Cannot access application directories on this system")

    def test_app_aliases_generation(self):
        """Test that app aliases are generated correctly."""
        try:
            aliases = self.controller.app_aliases
            self.assertIsInstance(aliases, dict)
            self.assertGreater(len(aliases), 0, "Should generate at least some aliases")

        except (OSError, PermissionError):
            self.skipTest("Cannot access application directories on this system")


if __name__ == "__main__":
    # Run the tests
    unittest.main(verbosity=2)
