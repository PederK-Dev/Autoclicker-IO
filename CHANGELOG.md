# Changelog

All notable changes to Autoclicker IO are documented here. This project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/).

## [Unreleased]

This is the ship-ready hardening track for the next Windows release.

### Added

- A global `Pause/Break` panic stop for active clicking, recording, and macro
  playback.
- A dismissible first-run safety guide and persistent Basic/Advanced view.
- Rotating diagnostic logs, versioned settings, validated backup recovery, and
  strict bounds checking for loaded macro files.
- Keyboard focus, activation, and navigation for the custom canvas controls.
- Windows packaging metadata, a repeatable PyInstaller build, and a release
  artifact workflow.
- Non-injecting hardening and accessibility coverage in the Windows test suite.

### Changed

- Documented safe defaults, data locations, troubleshooting, and the limits of
  Windows-only input automation.
- Hotkey editing now prevents conflicts except for the intentional shared
  Start/Stop toggle, and invalid numeric input must be corrected before a run.
- Action colors now retain WCAG AA text contrast across default, hover, pressed,
  and focus states in both themes.

## [1.0.0]

The initial Autoclicker IO release, including:

- Precise fixed and random click intervals with repeat limits and start delay.
- Left, middle, right, X1, and X2 clicks, including timed multi-clicks and
  optional cursor restoration.
- Configurable global keyboard and mouse-button hotkeys with suppression rules.
- Macro recording/playback, JSON persistence, named profiles, and dark/light
  themes with DPI-aware Tk rendering.

[Unreleased]: https://github.com/PederK-Dev/Autoclicker-IO/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/PederK-Dev/Autoclicker-IO/releases/tag/v1.0.0
