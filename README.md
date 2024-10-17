# <img src='https://rawgithub.com/FortAwesome/Font-Awesome/master/svgs/solid/spinner.svg' card_color='#22a7f0' width='50' height='50' style='vertical-align:bottom'/> Application Launcher

Application Launcher

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

## Configuration Options in `settings.json`

To customize the behavior of the Application Launcher skill, you can modify the following options in the `settings.json` file:

| Option               | Type                   | Default Value                             | Description                                                                                                                        |
|----------------------|------------------------|-------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| `aliases`            | `Dict[str, List[str]]` | `{"kcalc": ["calculator"]}`               | Defines application aliases. Use application names from the `.desktop` file as keys and a list of speech-friendly names as values. |
| `user_commands`      | `Dict[str, str]`       | `{}`                                      | User-defined application commands. Map application names to their corresponding bash commands.                                     |
| `thresh`             | `float`                | `0.85`                                    | The threshold for string matching. Lower values will allow more lenient matches for application names.                             |
| `skip_categories`    | `List[str]`            | `["Settings", "ConsoleOnly", "Building"]` | Categories in desktop files that exclude application from being considered.                                                        |
| `skip_keywords`      | `List[str]`            | `[]`                                      | Keywords in desktop files that exclude application from being considered.                                                          |
| `target_categories`  | `List[str]`            | `[]`                                      | Categories in desktop files required for application to be considered.                                                             |
| `target_keywords`    | `List[str]`            | `[]`                                      | Keywords in desktop files required for application to be considered.                                                               |
| `blacklist`          | `List[str]`            | `[]`                                      | List of applications to ignore during scanning (application names from the `.desktop` file).                                       |
| `require_icon`       | `bool`                 | `True`                                    | If set to `True`, only include applications that have an icon defined in their `.desktop` file.                                    |
| `require_categories` | `bool`                 | `True`                                    | If set to `True`, only include applications that have at least one category defined in their `.desktop` file.                      |
| `terminate_all`      | `bool`                 | `False`                                   | If `True`, will terminate all matching processes when closing applications.                                                        |
| `shell`              | `bool`                 | `False`                                   | If `True`, allows commands to be executed in a shell environment.                                                                  |

## Category

**Productivity**

## Tags

#desktop
#desktop-launch
#desktop-launcher
