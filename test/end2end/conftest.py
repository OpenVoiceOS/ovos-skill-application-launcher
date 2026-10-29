"""A stand-in for ovos-PHAL-plugin-app-launcher on the MiniCroft bus.

The skill asks the PHAL plugin over the bus to check, launch and close an
application. The stand-in answers that nothing is running, reports every
launch and close as a success, and records each request, so a test asserts
which application the skill asked for without touching a real process.
"""
import pytest

PHAL_LAUNCH = "ovos.phal.app_launcher.launch"
PHAL_CLOSE = "ovos.phal.app_launcher.close"
PHAL_IS_RUNNING = "ovos.phal.app_launcher.is_running"


def install_fake_phal(bus) -> list:
    """Answer the PHAL bus API on *bus*; return the list of
    ("launch" | "close", name) requests the skill sends."""
    calls = []

    def is_running(message):
        bus.emit(message.response({"name": message.data["name"], "running": False}))

    def action(verb):
        def handler(message):
            calls.append((verb, message.data["name"]))
            bus.emit(message.response({"name": message.data["name"], "success": True}))
        return handler

    bus.on(PHAL_IS_RUNNING, is_running)
    bus.on(PHAL_LAUNCH, action("launch"))
    bus.on(PHAL_CLOSE, action("close"))
    return calls


@pytest.fixture(scope="session")
def fake_phal():
    return install_fake_phal
