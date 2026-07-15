# <img src='https://rawgithub.com/FortAwesome/Font-Awesome/master/svgs/solid/spinner.svg' card_color='#22a7f0' width='50' height='50' style='vertical-align:bottom'/> Application Launcher

An OVOS skill that launches and closes applications on the Linux desktop by voice.

> **NOTE**: This skill works only on Linux desktop environments.

## Install

```bash
pip install ovos-skill-application-launcher
```

## About

The skill scans the standard directories for [.desktop files](https://wiki.archlinux.org/title/desktop_entries). It reads application names and execution commands from these files.

Scanned folders:

- /usr/share/applications/
- /usr/local/share/applications/
- ~/.local/share/applications/

## Examples

* "Open Volume Control"
* "Launch Firefox"
* "Close Firefox"

### Multiple instances of the same application

On Wayland systems, window control is not available. The skill closes apps only by ending running processes.

On X systems, the launcher closes windows before ending processes, if `wmctrl` is on your system.

This gives more granular control. You can manage multiple instances of an application, such as several Firefox windows, individually, even if they share the same PID.

If several processes with different PIDs match an application, the skill closes only the most recent one by default. You can turn on the old behavior, which ends all matching processes instead.

## Configuration via `settings.json`

To customize the behavior of the Application Launcher skill, you can modify the following options in the `settings.json` file:

| Option                   | Type                   | Default Value                             | Description                                                                                                                        |
|--------------------------|------------------------|-------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| `aliases`                | `Dict[str, List[str]]` | `{"kcalc": ["calculator"]}`               | Defines application aliases. Use application names from the `.desktop` file as keys and a list of speech-friendly names as values. |
| `user_commands`          | `Dict[str, str]`       | `{}`                                      | User-defined application commands. Map application names to their corresponding bash commands.                                     |
| `thresh`                 | `float`                | `0.85`                                    | The threshold for string matching. Lower values will allow more lenient matches for application names.                             |
| `skip_categories`        | `List[str]`            | `["Settings", "ConsoleOnly", "Building"]` | Categories in desktop files that exclude application from being considered.                                                        |
| `skip_keywords`          | `List[str]`            | `[]`                                      | Keywords in desktop files that exclude application from being considered.                                                          |
| `target_categories`      | `List[str]`            | `[]`                                      | Categories in desktop files required for application to be considered.                                                             |
| `target_keywords`        | `List[str]`            | `[]`                                      | Keywords in desktop files required for application to be considered.                                                               |
| `blacklist`              | `List[str]`            | `[]`                                      | List of applications to ignore during scanning (application names from the `.desktop` file).                                       |
| `require_icon`           | `bool`                 | `True`                                    | If set to `True`, only include applications that have an icon defined in their `.desktop` file.                                    |
| `require_categories`     | `bool`                 | `True`                                    | If set to `True`, only include applications that have at least one category defined in their `.desktop` file.                      |
| `terminate_all`          | `bool`                 | `False`                                   | If `True`, will terminate all matching processes when closing applications.                                                        |
| `shell`                  | `bool`                 | `False`                                   | If `True`, allows commands to be executed in a shell environment.                                                                  |
| `disable_window_manager` | `bool`                 | `False`                                   | If `True`, ignores `wmctl` and exclusively uses running processes for managing apps                                                |

eg.

```json
{
  "aliases": {
    "kcalc": ["calculator"]
  },
  "thresh": 0.85,
  "skip_categories": ["Settings", "ConsoleOnly", "Building"],
  "terminate_all": true
}
```

## Category

**Productivity**

## Tags

#desktop
#desktop-launch
#desktop-launcher

## License

Apache-2.0

## Credits

Developed by [TigreGótico](https://tigregotico.pt) for
[OpenVoiceOS](https://openvoiceos.org).

[![NGI0 Commons Fund](./ngi.png)](https://nlnet.nl/project/OpenVoiceOS)

This project was funded through the [NGI0 Commons Fund](https://nlnet.nl/commonsfund),
a fund established by [NLnet](https://nlnet.nl) with financial support from the
European Commission's [Next Generation Internet](https://ngi.eu) programme, under
the aegis of [DG Communications Networks, Content and Technology](https://commission.europa.eu/about-european-commission/departments-and-executive-agencies/communications-networks-content-and-technology_en)
under grant agreement No [101135429](https://cordis.europa.eu/project/id/101135429).
