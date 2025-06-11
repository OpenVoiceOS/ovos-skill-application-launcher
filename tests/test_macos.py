#!/usr/bin/env python3
"""
Simple test script to verify macOS app discovery functionality
"""

import os
import plistlib
from os.path import exists, expanduser, isdir, join
from typing import Dict, Generator, List, Union


def parse_app_bundle(app_path: str) -> Dict[str, Union[str, List[str]]]:
    """Parse a macOS .app bundle to extract relevant application metadata."""
    info_plist_path = join(app_path, "Contents", "Info.plist")
    if not exists(info_plist_path):
        return {}

    try:
        with open(info_plist_path, "rb") as f:
            plist_data = plistlib.load(f)
    except (plistlib.InvalidFileException, Exception) as e:
        # Handle malformed plist files gracefully
        print(f"DEBUG: Failed to parse {info_plist_path}: {e}")
        # Fall back to just using the app name from the directory
        app_name = os.path.basename(app_path).replace(".app", "")
        return {
            "name": app_name,
            "path": app_path,
            "bundle_id": "",
            "version": "",
        }

    app_name = plist_data.get("CFBundleName") or plist_data.get("CFBundleDisplayName") or ""
    if not app_name:
        # Fall back to the .app directory name
        app_name = os.path.basename(app_path).replace(".app", "")

    data = {
        "name": app_name,
        "path": app_path,
        "bundle_id": plist_data.get("CFBundleIdentifier", ""),
        "version": plist_data.get("CFBundleShortVersionString", ""),
    }

    return data


def get_macos_apps() -> Generator[Dict[str, Union[str, List[str]]], None, None]:
    """Retrieve macOS .app bundles."""
    # Standard macOS application directories - ordered by priority
    app_dirs = [
        "/Applications",
        "/System/Applications",
        "/Applications/Utilities",
        "/System/Library/CoreServices",
        "/System/Applications/Utilities",
        expanduser("~/Applications"),
    ]

    seen_apps = set()  # Track apps we've already found to avoid duplicates

    for app_dir in app_dirs:
        if not isdir(app_dir):
            continue

        try:
            for item in os.listdir(app_dir):
                if not item.endswith(".app"):
                    continue

                app_path = join(app_dir, item)
                if not isdir(app_path):
                    continue

                app_info = parse_app_bundle(app_path)

                if not app_info or not app_info.get("name"):
                    continue

                # Avoid duplicates (prefer system apps over user apps)
                app_key = str(app_info["name"]).lower()
                if app_key in seen_apps:
                    continue
                seen_apps.add(app_key)

                yield app_info
        except (OSError, PermissionError) as e:
            print(f"Could not access {app_dir}: {e}")
            continue


if __name__ == "__main__":
    print("Testing macOS app discovery...")
    apps = list(get_macos_apps())
    print(f"Found {len(apps)} applications")

    # Show first 10 apps
    for app in apps[:10]:
        print(f"  - {app['name']} at {app['path']}")

    # Test specific common apps
    common_apps = ["Safari", "Calculator", "Finder", "Terminal"]
    found_apps = {app["name"]: app["path"] for app in apps}

    print("\nLooking for common apps:")
    for app_name in common_apps:
        if app_name in found_apps:
            print(f"  ✓ {app_name}: {found_apps[app_name]}")
        else:
            print(f"  ✗ {app_name}: Not found")

    # Show all system apps for debugging
    print("\nAll found apps (first 20):")
    for i, app in enumerate(apps[:20]):
        print(f"  {i + 1:2d}. {app['name']} ({app.get('bundle_id', 'no bundle id')})")
