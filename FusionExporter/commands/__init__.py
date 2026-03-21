"""Command registry — start and stop all registered commands."""

import importlib

from .exportSVG import entry as exportSVG_entry

importlib.reload(exportSVG_entry)


def start():
    """Register all commands with Fusion 360."""
    exportSVG_entry.start()


def stop():
    """Remove all commands from Fusion 360."""
    exportSVG_entry.stop()
