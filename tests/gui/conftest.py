"""Run GUI tests without opening windows on screen (override with QT_QPA_PLATFORM=cocoa)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
