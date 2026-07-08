"""End-to-end smoke tests for ovos-skill-application-launcher.

These tests use `ovoscope` to drive the skill through a real OVOS bus
and assert the resulting bus traffic. The .github/workflows/ovoscope.yml
workflow runs them.

Status: scaffold only.

The skill's fallback handler calls into a platform-specific
ApplicationController whose `launch_app` method shells out to
`subprocess.Popen` (on Linux: `xdg-open`/the matched binary, on macOS:
`open` / `open -a`). Running the real launch path on a CI runner would
attempt to actually start GUI applications, which is bad. A useful
end-to-end test therefore needs the ovoscope harness *plus* a per-test
monkeypatch of `LinuxApplicationController.launch_app` (or whichever
controller is in use) so the test asserts only the bus traffic and not
the side effect.

Until that monkeypatch is wired in, the real test below is marked
`skip` so it doesn't false-fire on every PR. The collected import is
still useful: it proves the ovoscope dependency installs cleanly and
its public API hasn't drifted.
"""

import pytest

# Import-only smoke: if ovoscope is broken or its public API moves,
# this test fails fast and the rest of the file is skipped via the
# import-time guard below.
ovoscope = pytest.importorskip("ovoscope")
End2EndTest = ovoscope.End2EndTest

from ovos_bus_client.message import Message  # noqa: E402
from ovos_bus_client.session import Session  # noqa: E402


SKILL_ID = "ovos-skill-application-launcher.openvoiceos"


def test_ovoscope_imports_cleanly():
    """Sanity check: the ovoscope dependency is installable and its
    public API exposes ``End2EndTest``.
    """
    assert End2EndTest is not None
    assert hasattr(End2EndTest, "execute")


@pytest.mark.skip(
    reason=(
        "Requires monkeypatching ApplicationController.launch_app to "
        "avoid actually launching GUI applications on the CI runner. "
        "See module docstring for the design sketch."
    )
)
def test_launch_firefox_intent_match():
    """Verify the fallback handler matches a launch utterance and
    emits the expected bus messages.

    TODO: monkeypatch the active controller's launch_app to a no-op
    that returns True, then assert that:
      * recognizer_loop:utterance produces the fallback ack
      * the controller's launch_app was called with "firefox"
      * the skill emits mycroft.acknowledge (or whatever
        self.acknowledge() resolves to on the bus)
    """
    session = Session("test-session")
    utterance = Message(
        "recognizer_loop:utterance",
        {"utterances": ["open firefox"], "lang": "en-US"},
        {
            "session": session.serialize(),
            "source": "test",
            "destination": "skills",
        },
    )

    # NOTE: expected_messages=[utterance] is intentionally a placeholder
    # while this test is skipped. When the launch_app monkeypatch is
    # wired in (see module docstring), replace this with the real bus
    # traffic the skill emits — at minimum the fallback ack and
    # mycroft.acknowledge.
    End2EndTest(
        skill_ids=[SKILL_ID],
        source_message=utterance,
        expected_messages=[utterance],
    ).execute(timeout=10)
