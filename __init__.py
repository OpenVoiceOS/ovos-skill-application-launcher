from os import listdir
from os.path import expanduser, isdir, join
import os
from mycroft.skills import FallbackSkill
from mycroft.util.parse import match_one
from padacioso import IntentContainer


class ApplicationLauncherSkill(FallbackSkill):
    def initialize(self):
        for app in self.get_app_aliases().keys():
            self.register_vocabulary(app.lower(), "Application")
        # some applications can't be easily triggered by voice
        # this is a mapping of alternative names that should be accounted for
        if "aliases" not in self.settings:
            self.settings["aliases"] = {
                # "name from .desktop file": ["speech", "friendly", "names"]
                "kcalc": "calculator"
            }
        # this is a regex based intent parser
        # we handle this in fallback stage to
        # allow more control over matching application names
        self.container = IntentContainer()
        self.register_fallback_intents()
        # before common_query, otherwise we get info about the app instead
        self.register_fallback(self.handle_fallback, 4)

    def register_fallback_intents(self):
        # TODO close application intent
        launch = join(self.root_dir, "locale", self.lang, "launch.intent")
        with open(launch) as f:
            self.container.add_intent('launch', f.read().split("\n"))

    def get_app_aliases(self):
        apps = {}
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
        return apps

    def handle_fallback(self, message):
        utterance = message.data.get("utterance", "")
        res = self.container.calc_intent(utterance)
        app = res.get('entities', {}).get("application")
        if app:
            applist = self.get_app_aliases()
            cmd, score = match_one(app.title(), applist)
            if score >= self.settings.get("thresh", 0.85):
                self.log.info(f"Executing command: {cmd}")
                os.system(cmd)
                return True


def create_skill():
    return ApplicationLauncherSkill()
