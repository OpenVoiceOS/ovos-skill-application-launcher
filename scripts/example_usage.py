#!/usr/bin/env python3
"""
Example usage of MacOSApplicationController

This demonstrates how to use the refactored macOS application management
functionality independently of the voice assistant.
"""

import time

from macos_controller import MacOSApplicationController


def main():
    """Demonstrate MacOSApplicationController usage."""

    # Initialize the controller with custom settings
    settings = {
        "thresh": 0.85,  # Matching threshold
        "aliases": {
            "Calculator": ["calculator", "calc"],
            "Safari": ["browser", "web browser"],
            "Terminal": ["command line", "shell"],
        },
        "user_commands": {
            # You can add custom app paths here
            # "MyApp": "/Applications/MyCustomApp.app"
        },
        "blocklist": [
            # Apps to ignore during discovery
            "System Information.app",
        ],
        "extra_langs": ["en-US"],
        "disable_window_manager": False,
        "terminate_all": False,
    }

    controller = MacOSApplicationController(settings)

    print("=== MacOS Application Controller Demo ===\n")

    # 1. Discover applications
    print("1. Discovering applications...")
    app_aliases = controller.app_aliases
    print(f"Found {len(app_aliases)} applications and aliases")

    # Show first 10 apps
    print("\nFirst 10 applications:")
    for i, (name, path) in enumerate(list(app_aliases.items())[:10]):
        print(f"  {i + 1:2d}. {name} -> {path}")

    # 2. Check if specific apps are available
    print("\n2. Checking for common applications...")
    common_apps = ["Safari", "Calculator", "Terminal", "Finder"]
    available_apps = []

    for app in common_apps:
        if app in app_aliases:
            print(f"  ✓ {app} is available")
            available_apps.append(app)
        else:
            print(f"  ✗ {app} is not found")

    if not available_apps:
        print("No common apps found for demo. Exiting.")
        return

    # 3. Demonstrate launching an app
    demo_app = available_apps[0]  # Use the first available app
    print(f"\n3. Demonstrating app management with {demo_app}...")

    # Check if app is running
    is_running_before = controller.is_running(demo_app)
    print(f"   {demo_app} running before: {is_running_before}")

    # Launch the app
    print(f"   Launching {demo_app}...")
    launch_success = controller.launch_app(demo_app)
    print(f"   Launch successful: {launch_success}")

    if launch_success:
        # Wait a moment for the app to start
        time.sleep(2)

        # Check if app is now running
        is_running_after = controller.is_running(demo_app)
        print(f"   {demo_app} running after launch: {is_running_after}")

        if is_running_after:
            # Try switching to the app
            print(f"   Switching to {demo_app}...")
            switch_success = controller.switch_to_app(demo_app)
            print(f"   Switch successful: {switch_success}")

            # Wait a moment
            time.sleep(2)

            # Try closing the app gracefully
            print(f"   Closing {demo_app} gracefully...")
            close_success = controller.close_app(demo_app)
            print(f"   Close successful: {close_success}")

            # Wait and check if it's still running
            time.sleep(1)
            is_running_final = controller.is_running(demo_app)
            print(f"   {demo_app} running after close: {is_running_final}")

    # 4. Demonstrate app bundle parsing
    print("\n4. Demonstrating app bundle parsing...")
    if demo_app in app_aliases:
        app_path = app_aliases[demo_app]
        if app_path.endswith(".app"):
            bundle_info = controller.parse_app_bundle(app_path)
            if bundle_info:
                print(f"   App: {bundle_info.get('name', 'Unknown')}")
                print(f"   Bundle ID: {bundle_info.get('bundle_id', 'Unknown')}")
                print(f"   Version: {bundle_info.get('version', 'Unknown')}")
                print(f"   Localized names: {bundle_info.get('localized_names', [])}")

    # 5. Demonstrate process matching
    print("\n5. Demonstrating process matching...")
    processes = list(controller.match_process(demo_app))
    print(f"   Found {len(processes)} matching processes for {demo_app}")
    for proc in processes[:3]:  # Show first 3 processes
        try:
            print(f"   - PID {proc.info['pid']}: {proc.info['name']}")
        except Exception:
            print("   - Process info unavailable")

    print("\n=== Demo Complete ===")


if __name__ == "__main__":
    main()
