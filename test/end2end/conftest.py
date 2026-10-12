"""A fake desktop for the golden runners.

The skill's own ``launch_app`` and ``close_app`` run unchanged against a
fixed application list. ``subprocess.Popen`` and ``psutil.process_iter`` in
the skill module are replaced, so a launch records the command the skill
resolved and a close records the process it terminated. Nothing on the host
starts or stops.
"""
import sys
from types import SimpleNamespace

import psutil
import pytest

# speech name (as the skill title-cases it) -> command
FAKE_APPS = {
    "Firefox": "firefox",
    "فایرفاکس": "firefox",
    "Spotify": "spotify",
    "Thunderbird": "thunderbird",
    "Vlc": "vlc",
    "Gimp": "gimp",
    "Libreoffice": "libreoffice",
    "Terminal": "terminal",
    "Calculator": "kcalc",
    "Calculadora": "kcalc",
    "Calculatrice": "kcalc",
    "Calcolatrice": "kcalc",
    "Lommeregneren": "kcalc",
    "Taschenrechner": "kcalc",
    "Rekenmachine": "kcalc",
    "Miniräknaren": "kcalc",
}


class _FakeProcess:
    def __init__(self, name, record):
        self.info = {"pid": abs(hash(name)) % 30000, "name": name, "create_time": 0.0}
        self._record = record

    def status(self):
        return "running"

    def terminate(self):
        self._record(("close", self.info["name"]))


def expected_command(app: str) -> str:
    return FAKE_APPS[app.title()]


def _install(skill):
    """Point the skill at the fake desktop.

    ``skill.attempts`` records every (action, slot value) the handler passes to
    launch_app/close_app; ``skill.calls`` records what the skill's own matching
    then did: ("launch", command) or ("close", process name).
    """
    module = sys.modules[type(skill).__module__]
    saved = (module.subprocess, module.psutil)
    skill.attempts, skill.calls = [], []
    record = skill.calls.append
    processes = [_FakeProcess(cmd, record) for cmd in sorted(set(FAKE_APPS.values()))]
    module.subprocess = SimpleNamespace(Popen=lambda args, shell=False: record(("launch", " ".join(args))))
    module.psutil = SimpleNamespace(process_iter=lambda attrs=None: list(processes),
                                    NoSuchProcess=psutil.NoSuchProcess,
                                    AccessDenied=psutil.AccessDenied)
    skill.applist = dict(FAKE_APPS)
    skill.wmctrl = None
    skill.is_running = lambda app: False
    launch, close = skill.launch_app, skill.close_app
    skill.launch_app = lambda app: skill.attempts.append(("launch", app)) or launch(app)
    skill.close_app = lambda app: skill.attempts.append(("close", app)) or close(app)

    def restore():
        module.subprocess, module.psutil = saved

    return restore


@pytest.fixture(scope="session")
def fake_desktop():
    return SimpleNamespace(install=_install, expected_command=expected_command)
