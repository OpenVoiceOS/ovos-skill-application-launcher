"""close_by_process must terminate nothing when no application matches.

match_process asked match_one for the closest known application and threw the
score away, so every {application} value picked some installed program. With
the close phrasings "shut off ...", "shut ... down" and "i want to close ...",
ordinary requests such as "shut off the lights" terminated Lightworks. The
process table below is fake: each process records a terminate() call, and no
real process is touched.
"""
import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from ovos_utils.fakebus import FakeBus

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_skill_module():
    spec = importlib.util.spec_from_file_location(
        "appl_skill_match_process", os.path.join(REPO, "__init__.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["appl_skill_match_process"] = module
    spec.loader.exec_module(module)
    return module


class FakeProcess:
    def __init__(self, pid, name, create_time):
        self.info = {"pid": pid, "name": name, "create_time": create_time}
        self.terminated = False

    def status(self):
        return "running"

    def terminate(self):
        self.terminated = True


@pytest.fixture
def skill_and_table():
    module = _load_skill_module()
    skill = module.ApplicationLauncherSkill(skill_id="test.app.launcher.process", bus=FakeBus())
    skill.acknowledge = MagicMock()
    skill.applist = {"Firefox": "firefox", "Lightworks": "lightworks", "Spotify": "spotify"}
    table = [FakeProcess(101, "firefox", 3.0),
             FakeProcess(102, "lightworks", 2.0),
             FakeProcess(103, "spotify", 1.0)]
    with patch.object(module.psutil, "process_iter", return_value=table):
        yield skill, table


@pytest.mark.parametrize("app", ["the lights", "the heater", "the alarm", "my eyes", "the deal"])
def test_unrelated_value_terminates_nothing(skill_and_table, app):
    skill, table = skill_and_table
    assert skill.close_by_process(app) is False
    assert [p.info["name"] for p in table if p.terminated] == []


@pytest.mark.parametrize("app", ["spotify", "firefox"])
def test_known_application_terminates_only_itself(skill_and_table, app):
    skill, table = skill_and_table
    assert skill.close_by_process(app) is True
    assert [p.info["name"] for p in table if p.terminated] == [app]
