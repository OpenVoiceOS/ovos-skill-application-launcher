# <img src='https://rawgithub.com/FortAwesome/Font-Awesome/master/svgs/solid/spinner.svg' card_color='#22a7f0' width='50' height='50' style='vertical-align:bottom'/> Mac Application Launcher

Launch macOS applications by voice

> **NOTE**: This skill only works on macOS systems!

## About

Launch applications on macOS using voice commands through OVOS (Open Voice OS).

The skill automatically discovers applications by scanning standard macOS application directories and parsing `.app` bundles to extract application metadata including names, bundle identifiers, and versions.

Scanned directories:

- `/Applications`
- `/System/Applications`
- `/Applications/Utilities`
- `/System/Library/CoreServices`
- `/System/Applications/Utilities`
- `~/Applications`

## Examples

- "Open Safari"
- "Launch Calculator"
- "Close Terminal"
- "Switch to Finder"

### Application Management

The skill provides comprehensive application management:

- **Launch**: Start applications that aren't running
- **Switch**: Bring running applications to the foreground
- **Close**: Gracefully quit applications using AppleScript, falling back to process termination if needed
- **Status**: Check if applications are currently running

The skill prioritizes graceful application closure using AppleScript's quit commands, which allows applications to save their state properly. If AppleScript fails, it falls back to process termination.

## Configuration via `settings.json`

Customize the Application Launcher skill behavior by modifying these options in `settings.json`:

| Option                   | Type                   | Default Value | Description                                                                                           |
| ------------------------ | ---------------------- | ------------- | ----------------------------------------------------------------------------------------------------- |
| `aliases`                | `Dict[str, List[str]]` | `{}`          | Application aliases. Map app names to speech-friendly alternatives (e.g., `{"Calculator": ["calc"]}`) |
| `user_commands`          | `Dict[str, str]`       | `{}`          | Custom application paths. Map app names to specific `.app` bundle paths                               |
| `thresh`                 | `float`                | `0.85`        | Fuzzy matching threshold for application names. Lower values allow more lenient matches               |
| `blocklist`              | `List[str]`            | `[]`          | Applications to exclude from voice control                                                            |
| `extra_langs`            | `List[str]`            | `["en-US"]`   | Additional language codes for intent matching                                                         |
| `disable_window_manager` | `bool`                 | `False`       | If `True`, disables AppleScript-based window management                                               |
| `terminate_all`          | `bool`                 | `False`       | If `True`, terminates all matching processes when closing applications                                |

Example configuration:

```json
{
  "aliases": {
    "Calculator": ["calc", "calculator"],
    "Safari": ["browser", "web browser"],
    "Terminal": ["term", "console"]
  },
  "thresh": 0.85,
  "blocklist": ["System Preferences"],
  "terminate_all": false
}
```

## Installation

Install from PyPI:

```bash
pip install skill-mac-application-launcher
```

Or install from source:

```bash
git clone https://github.com/OscillateLabsLLC/skill-mac-application-launcher
cd skill-mac-application-launcher
pip install .
```

## Development

For development, install with dev dependencies:

```bash
pip install -e .[dev]
```

Run tests:

```bash
pytest
```

Run type checking:

```bash
mypy skill_mac_application_launcher/
```

Run linting:

```bash
ruff check skill_mac_application_launcher/ tests/
```

## Category

**Productivity**

## Tags

#macos
#application-launcher
#voice-control
#ovos
