"""E2E intent-routing tests for ovos-skill-application-launcher (en-US).

``ApplicationLauncherSkill`` is a ``FallbackSkill``: it never registers
padacioso/padatious skill intents, it resolves ``launch``/``close`` utterances
inside its fallback handler via an internal ``IntentContainer`` built from the
``locale/<lang>/{launch,close}.intent`` templates. These tests therefore drive
the utterances through the fallback pipeline on a real MiniCroft bus and assert
the skill performs the (mocked) OS-level action and reports the utterance as
handled. Only ``subprocess.Popen`` is mocked -- no real application is started.

Run: pytest test/end2end/ -v
"""
import os
import tempfile

# Isolate XDG dirs per xdist worker *before* any ovos config import: parallel
# workers otherwise share ~/.config/mycroft/skills and race to create the same
# skill directory (FileExistsError on load).
_worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
_iso = os.path.join(tempfile.gettempdir(), f"ovos-e2e-app-launcher-{_worker}")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_iso, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_iso, "data")
os.environ["XDG_CACHE_HOME"] = os.path.join(_iso, "cache")

import time
from unittest import TestCase
from unittest.mock import patch

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovoscope import get_minicroft

from ovos_skill_application_launcher import ApplicationLauncherSkill

SKILL_ID = "ovos-skill-application-launcher.openvoiceos"
LANG = "en-US"

# The default alias map ships "kcalc" -> ["calculator"], so "calculator"
# resolves deterministically to the "kcalc" command regardless of the
# .desktop files present on the CI host.
APP_NAME = "calculator"
APP_CMD = "kcalc"

# Fallback skills resolve through the fallback pipeline, never a padacioso
# activation message, so the session pipeline must contain the fallback tiers.
FALLBACK_PIPELINE = [
    "ovos-fallback-pipeline-plugin-high",
    "ovos-fallback-pipeline-plugin-medium",
    "ovos-fallback-pipeline-plugin-low",
]


class TestFallbackRoutingEnUS(TestCase):
    """launch/close utterances route to the skill's fallback handler."""

    @classmethod
    def setUpClass(cls):
        # never scan the host's real .desktop files: results are
        # non-deterministic and some system entries carry locale suffixes
        # (e.g. Name[sr@latin]) that crash langcodes on load (issue #91).
        # a plain function (not a MagicMock) is used so the fallback-handler
        # decorator scanner does not mistake the stub for a decorated method.
        cls._desktop_patch = patch.object(
            ApplicationLauncherSkill,
            "get_desktop_apps",
            new=lambda self, **kwargs: [],
        )
        cls._desktop_patch.start()
        cls.minicroft = get_minicroft([SKILL_ID])
        cls.skill = cls.minicroft.plugin_skills[SKILL_ID].instance
        # pin a known app so matching never depends on the host's apps
        cls.skill.applist = {"Calculator": APP_CMD}
        # headless CI has no window manager; keep close routing deterministic
        cls.skill.wmctrl = None

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "minicroft", None):
            cls.minicroft.stop()
        cls._desktop_patch.stop()

    def _drive(self, utterance: str, session_id: str) -> Message:
        session = Session(session_id)
        session.lang = LANG
        session.pipeline = FALLBACK_PIPELINE
        message = Message(
            "recognizer_loop:utterance",
            {"utterances": [utterance], "lang": LANG},
            {"session": session.serialize()},
        )
        handled = []
        self.minicroft.bus.on("ovos.utterance.handled", handled.append)
        self.minicroft.bus.emit(message)
        deadline = time.monotonic() + 10
        while not handled and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(handled, f"utterance '{utterance}' was not handled")
        return handled[-1]

    def test_launch_application(self):
        """'launch <app>' triggers the (mocked) launch of the resolved cmd."""
        with patch(
            "ovos_skill_application_launcher.subprocess.Popen"
        ) as popen:
            self._drive(f"launch {APP_NAME}", "e2e-en_us-launch")
            self.assertTrue(popen.called, "skill never launched the app")
            self.assertEqual(popen.call_args.args[0], [APP_CMD])

    def test_close_application(self):
        """'close <app>' routes to the fallback handler's close branch."""
        # process/window termination is faked so the test never touches real
        # OS state; asserting close_by_process ran proves the close routing.
        with patch.object(
            self.skill, "close_by_process", return_value=True
        ) as close:
            self._drive(f"close {APP_NAME}", "e2e-en_us-close")
            close.assert_called_once_with(APP_NAME)
