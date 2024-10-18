# <img src='https://rawgithub.com/FortAwesome/Font-Awesome/master/svgs/solid/spinner.svg' card_color='#22a7f0' width='50' height='50' style='vertical-align:bottom'/> Application Launcher

Application Launcher

> **NOTE**: this skill only works on Linux desktop environments!

## About

Launch applications on the Linux desktop

The standard directories will be scanned for [.desktop files](https://wiki.archlinux.org/title/desktop_entries),
application names and execution commands will be parsed from there

Scanned folders:

- /usr/share/applications/
- /usr/local/share/applications/
- ~/.local/share/applications/

## Examples

* "Open Volume Control"
* "Launch Firefox"
* "Close Firefox"

### Multiple instances of same Application

In Wayland systems window control is not available and apps are closed exclusively by terminating running processes

In X systems, the launcher prioritizes closing windows over terminating processes if `wmctrl` is available in your system

This provides a more granular control, allowing multiple instances of applications (such as several Firefox windows) to be managed individually. Even if they share the same PID

If multiple processes with different PIDs match a specific application, it will only close the most recent one by default. However, users can opt for the old behavior, which allows the option to kill all matching processes.

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
