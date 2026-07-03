"""End-to-end intent-routing coverage for ovos-skill-application-launcher.

The skill does not register regular intents; it exposes a single fallback
handler (priority 4) that matches "open/launch/close <application>" utterances
through its own padacioso containers and then launches or closes the desktop
application. These tests drive the fallback pipeline with representative
utterances and assert the fallback message skeleton.

The real launch/close code paths spawn OS processes and inspect the running
process table, which is not deterministic on a CI runner, so the instance's
launch/close side effects are neutralised while the intent-matching and
fallback routing under test run for real.
"""
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft

SKILL_ID = "ovos-skill-application-launcher.openvoiceos"
LANG = "en-US"
HANDLER = "ApplicationLauncherSkill.handle_fallback"


class _FallbackRoutingMixin:
    """Boot one MiniCroft and stub the OS-facing launch/close side effects."""

    @classmethod
    def setUpClass(cls):
        LOG.set_level("CRITICAL")
        cls.minicroft = get_minicroft([SKILL_ID])
        cls.skill = cls.minicroft.plugin_skills[SKILL_ID].instance
        # keep intent matching real; neutralise the OS-facing effects so the
        # outcome does not depend on which applications happen to be installed
        # or running on the runner
        cls.skill.is_running = lambda app: False
        cls.skill.launch_app = lambda app: True
        cls.skill.close_app = lambda app: True

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "minicroft", None):
            cls.minicroft.stop()

    def _assert_fallback(self, utterance: str):
        session = Session(f"e2e-{hash(utterance)}")
        session.lang = LANG
        # priority-4 handler lives in the high-priority fallback range
        session.pipeline = ["ovos-fallback-pipeline-plugin-high"]

        message = Message(
            "recognizer_loop:utterance",
            {"utterances": [utterance], "lang": LANG},
            {"session": session.serialize()},
        )

        expected_messages = [
            message,
            Message("ovos.skills.fallback.ping",
                    {"utterances": [utterance], "lang": LANG}),
            Message("ovos.skills.fallback.pong",
                    {"skill_id": SKILL_ID, "can_handle": True},
                    {"skill_id": SKILL_ID}),
            Message(f"ovos.skills.fallback.{SKILL_ID}.request",
                    {"skill_id": SKILL_ID}),
            Message(f"ovos.skills.fallback.{SKILL_ID}.start", {}),
            Message(f"ovos.skills.fallback.{SKILL_ID}.response",
                    {"result": True, "fallback_handler": HANDLER}),
            Message("ovos.utterance.handled", {}),
        ]

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            ignore_messages=["speak", "ovos.utterance.speak",
                             "mycroft.audio.play_sound"],
            source_message=message,
            expected_messages=expected_messages,
        )
        test.execute()


class TestLaunchRouting(_FallbackRoutingMixin, TestCase):
    def test_open_firefox(self):
        self._assert_fallback("open firefox")

    def test_launch_spotify(self):
        self._assert_fallback("launch spotify")


class TestCloseRouting(_FallbackRoutingMixin, TestCase):
    def test_close_chrome(self):
        self._assert_fallback("close chrome")
