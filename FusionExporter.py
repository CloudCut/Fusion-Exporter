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

importlib.reload(config)
importlib.reload(commands)


def run(context):
    """Called when the add-in is started."""
    try:
        commands.start()
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
