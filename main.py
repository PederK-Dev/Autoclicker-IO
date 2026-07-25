"""Launch Autoclicker IO."""

import sys

from autoclicker.ui import run

if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("Autoclicker IO uses the Win32 input APIs and is Windows-only.")
    run()
