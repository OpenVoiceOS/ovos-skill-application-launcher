import os
import shlex
import subprocess
import time
from os import listdir
from os.path import expanduser, isdir, join

import psutil
from langcodes import closest_match
from ovos_utils.bracket_expansion import expand_options
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.log import LOG
from ovos_utils.parse import match_one, fuzzy_match
from ovos_workshop.skills.fallback import FallbackSkill
from padacioso import IntentContainer


class ApplicationLauncherSkill(FallbackSkill):
    def initialize(self):
        # some applications can't be easily triggered by voice
        # this is a mapping of alternative names that should be accounted for
        if "aliases" not in self.settings:
            self.settings["aliases"] = {
                # "name from .desktop file": ["speech", "friendly", "names"]
                "kcalc": ["calculator"]
            }
        # these are user defined commands mapped to voice
        if "user_commands" not in self.settings:
            # "application name": "bash command"
            self.settings["user_commands"] = {}

        # this is a regex based intent parser
        # we handle this in fallback stage to
        # allow more control over matching application names
        self.intent_matchers = {}
        self.register_fallback_intents()
        # before common_query, otherwise we get info about the app instead
        self.register_fallback(self.handle_fallback, 4)

    def register_fallback_intents(self):
        intents = ["close", "launch"]
        for lang in os.listdir(f"{self.root_dir}/locale"):
            for intent_name in intents:
                launch = join(self.root_dir, "locale", lang, f"{intent_name}.intent")
                if not os.path.isfile(launch):
                    continue
                lang = standardize_lang_tag(lang)
                if lang not in self.intent_matchers:
                    self.intent_matchers[lang] = IntentContainer()
                with open(launch) as f:
                    samples = [option for line in f.read().split("\n")
                               if not line.startswith("#") and line.strip()
                               for option in expand_options(line)]
                    self.intent_matchers[lang].add_intent(intent_name, samples)

    def get_app_aliases(self):
        apps = self.settings.get("user_commands") or {}
        norm = lambda k: k.replace(".desktop", "").replace("-", " ").replace("_", " ").split(".")[-1].title()
        for p in ["/usr/share/applications/",
                  "/usr/local/share/applications/",
                  expanduser("~/.local/share/applications/")]:
            if not isdir(p):
                continue
            for f in listdir(p):
                path = join(p, f)
                names = [norm(f)]
                cmd = ""
                is_app = True
                if os.path.isdir(path):
                    continue
                with open(path) as fi:
                    for l in fi.read().split("\n"):
                        if "Name=" in l:
                            name = l.split("Name=")[-1]
                            names.append(norm(name))
                        if "GenericName=" in l:
                            name = l.split("GenericName=")[-1]
                            names.append(norm(name))
                        if "Comment=" in l:
                            name = l.split("Comment=")[-1]
                            names.append(norm(name))
                        if "Exec=" in l:
                            cmd = l.split("Exec=")[-1]
                            name = cmd.split(" ")[0].split("/")[-1].split(".")[0]
                            names.append(norm(name))
                        if "Type=" in l:
                            t = l.split("Type=")[-1]
                            if "application" not in t.lower():
                                is_app = False

                if is_app and cmd:
                    for name in names:
                        if 3 <= len(name) <= 20:
                            apps[name] = cmd
                        # speech friendly aliases
                        if name in self.settings.get("aliases", {}):
                            for alias in self.settings["aliases"][name]:
                                apps[alias] = cmd
                        # KDE likes to replace every C with a K
                        if name.startswith("K"):
                            alias = "C" + name[1:]
                            if alias not in apps:
                                apps[alias] = cmd
                    LOG.debug(f"found app {f} with aliases: {names}")
        return apps

    def launch_app(self, app: str) -> bool:
        applist = self.get_app_aliases()
        cmd, score = match_one(app.title(), applist)
        if score >= self.settings.get("thresh", 0.85):
            LOG.info(f"Matched application: {app} (command: {cmd})")
            try:
                # Launch the application in a new process without blocking
                subprocess.Popen(shlex.split(cmd))
                return True
            except Exception as e:
                LOG.error(f"Failed to launch {app}: {e}")
        return False

    def close_app(self, app: str) -> bool:
        """Close the application with the given name."""
        applist = self.get_app_aliases()

        cmd, _ = match_one(app.title(), applist)
        cmd = cmd.split(" ")[0].split("/")[-1]
        terminated = []

        for proc in psutil.process_iter(['pid', 'name']):
            score = fuzzy_match(cmd, proc.info['name'])
            if score > 0.9:
                LOG.debug(f"Matched '{app}' to {proc}")
                try:
                    LOG.info(f"Terminating process: {proc.info['name']} (PID: {proc.info['pid']})")
                    proc.terminate()  # or process.kill() to forcefully kill
                    terminated.append(proc.info['pid'])

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    LOG.error(f"Failed to terminate {proc}")

        if terminated:
            LOG.debug(f"Terminated PIDs: {terminated}")
            return True
        return False

    def handle_fallback(self, message):

        utterance = message.data.get("utterance", "")
        best_lang, score = closest_match(self.lang, list(self.intent_matchers.keys()))

        if score >= 10:
            # unsupported lang
            return False

        best_lang = standardize_lang_tag(best_lang)

        res = self.intent_matchers[best_lang].calc_intent(utterance)

        app = res.get('entities', {}).get("application")
        if app:
            if res["name"] == "launch":
                return self.launch_app(app)
            elif res["name"] == "close":
                return self.close_app(app)


if __name__ == "__main__":
    LOG.set_level("DEBUG")
    from ovos_utils.fakebus import FakeBus
    from ovos_bus_client.message import Message

    s = ApplicationLauncherSkill(skill_id="fake.test", bus=FakeBus())
    s.handle_fallback(Message("", {"utterance": "abrir firefox", "lang": "pt-pt"}))
    time.sleep(2)
    # s.handle_fallback(Message("", {"utterance": "kill firefox"}))
    time.sleep(2)
    s.handle_fallback(Message("", {"utterance": "launch firefox", "lang": "en-UK"}))
