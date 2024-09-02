import os
from os import listdir
from os.path import expanduser, isdir, join

from ovos_utils.log import LOG
from ovos_utils.parse import match_one
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
        # TODO close application intent
        for lang in os.listdir(f"{self.root_dir}/locale"):
            self.intent_matchers[lang] = IntentContainer()
            launch = join(self.root_dir, "locale", self.lang, "launch.intent")
            with open(launch) as f:
                samples = [l for l in f.read().split("\n")
                           if not l.startswith("#") and l.strip()]
                self.intent_matchers[lang].add_intent('launch', samples)

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
                with open(path) as f:
                    for l in f.read().split("\n"):
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

    def handle_fallback(self, message):

        utterance = message.data.get("utterance", "")
        if self.lang not in self.intent_matchers:
            return False

        res = self.intent_matchers[self.lang].calc_intent(utterance)
        app = res.get('entities', {}).get("application")
        if app:
            applist = self.get_app_aliases()
            cmd, score = match_one(app.title(), applist)
            if score >= self.settings.get("thresh", 0.85):
                LOG.info(f"Executing command: {cmd}")
                os.system(cmd)
                return True


if __name__ == "__main__":
    from ovos_utils.fakebus import FakeBus
    from ovos_bus_client.message import Message

    s = ApplicationLauncherSkill(skill_id="fake.test", bus=FakeBus())
    s.handle_fallback(Message("", {"utterance": "launch firefox"}))
