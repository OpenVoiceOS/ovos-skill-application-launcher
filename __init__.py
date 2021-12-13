import os
from os import listdir
from os.path import expanduser, isdir, join

from adapt.intent import IntentBuilder
from mycroft.skills import MycroftSkill, intent_handler
from mycroft.util.parse import match_one


class ApplicationLauncherSkill(MycroftSkill):

    def initialize(self):
        for app in self.get_app_aliases().keys():
            self.register_vocabulary(app.lower(), "Application")

    @staticmethod
    def get_app_aliases():
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
        return apps

    @intent_handler(IntentBuilder("LaunchApplication").
                    require("Launch").require("Application"))
    def handle_open_application(self, message):
        app = message.data["Application"]
        applist = self.get_app_aliases()
        cmd, _ = match_one(app.title(), applist)
        os.system(cmd)


def create_skill():
    return ApplicationLauncherSkill()
