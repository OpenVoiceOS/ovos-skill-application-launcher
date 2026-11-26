# <img src='https://rawgithub.com/FortAwesome/Font-Awesome/master/svgs/solid/spinner.svg' card_color='#22a7f0' width='50' height='50' style='vertical-align:bottom'/> Application Launcher

An OVOS skill that launches and closes applications on the Linux desktop by voice.

> **NOTE**: This skill works only on Linux desktop environments.

## Install

```bash
pip install ovos-skill-application-launcher
```

This skill only understands "open/launch/close &lt;application&gt;" voice
commands and speaks the result; it does no OS-level work itself. Launching,
closing and checking whether an application is running all happen over the
message bus, handled by the
[ovos-PHAL-plugin-app-launcher](https://github.com/OpenVoiceOS/ovos-PHAL-plugin-app-launcher)
PHAL plugin. Without that plugin installed and running, the skill still
matches your utterances but can't actually do anything -- it tells you the
launcher service isn't available. See that plugin's README for the settings
that control which applications it finds and how it launches/closes them
(desktop-file scanning, aliases, `wmctrl`, etc).

Because the skill only talks to the PHAL plugin over the bus, the plugin
doesn't have to run on the same device as the skill -- it works across
HiveMind too.

## Examples

* "Open Volume Control"
* "Launch Firefox"
* "Close Firefox"

## Category

**Productivity**

## Tags

#desktop
#desktop-launch
#desktop-launcher

## License

Apache-2.0
