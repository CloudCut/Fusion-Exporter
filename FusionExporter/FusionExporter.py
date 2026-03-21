"""FusionExporter — Fusion 360 Add-in Entry Point.

Exports design geometry as SVG files for CNC toolpath generation.
"""

import adsk.core
import adsk.fusion
import traceback
import os
import sys

# Add add-in directory to sys.path for absolute imports
ADDIN_DIR = os.path.dirname(os.path.abspath(__file__))
if ADDIN_DIR not in sys.path:
    sys.path.insert(0, ADDIN_DIR)

import importlib
import config
import commands
from lib import updater

importlib.reload(config)
importlib.reload(commands)
importlib.reload(updater)


def _notify_update_available(version):
    """Called from the background thread when a new version has been staged."""
    try:
        app = adsk.core.Application.get()
        if app and app.userInterface:
            app.userInterface.messageBox(
                'FusionExporter v{} has been downloaded.\n\n'
                'Please restart Fusion 360 to apply the update.'.format(version)
            )
    except Exception:
        pass


def run(context):
    """Called when the add-in is started."""
    try:
        # Apply any previously staged update before loading anything else
        if updater.apply_staged_update():
            # Reload modules so the new code takes effect this session
            importlib.reload(config)
            importlib.reload(commands)

        commands.start()

        # Check for updates in the background
        updater.check_for_update(_notify_update_available)
    except Exception:
        app = adsk.core.Application.get()
        if app and app.userInterface:
            app.userInterface.messageBox(
                'Failed to start FusionExporter:\n{}'.format(traceback.format_exc())
            )


def stop(context):
    """Called when the add-in is stopped."""
    try:
        commands.stop()
    except Exception:
        app = adsk.core.Application.get()
        if app and app.userInterface:
            app.userInterface.messageBox(
                'Failed to stop FusionExporter:\n{}'.format(traceback.format_exc())
            )
