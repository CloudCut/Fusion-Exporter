"""CloudCut Exporter — Fusion 360 Add-in Entry Point.

Exports design geometry as SVG files for CNC toolpath generation.
"""

import adsk.core
import adsk.fusion
import traceback
import os
import sys
import json

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

# Custom event for thread-safe UI notification
_UPDATE_EVENT_ID = 'CloudCutExporterUpdateEvent'
_custom_event = None
_update_handler = None


class _UpdateEventHandler(adsk.core.CustomEventHandler):
    """Handles the update notification on Fusion's main thread."""
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            event_args = json.loads(args.additionalInfo)
            version = event_args.get('version', '?')
            app = adsk.core.Application.get()
            if app and app.userInterface:
                app.userInterface.messageBox(
                    'CloudCut Exporter v{} has been downloaded.\n\n'
                    'Please restart Fusion 360 to apply the update.'.format(version)
                )
        except Exception:
            pass


def _notify_update_available(version):
    """Called from the background thread — fires a custom event to reach the main thread."""
    try:
        app = adsk.core.Application.get()
        if app:
            app.fireCustomEvent(_UPDATE_EVENT_ID, json.dumps({'version': version}))
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

        # Register custom event for thread-safe update notifications
        global _custom_event, _update_handler
        app = adsk.core.Application.get()
        _custom_event = app.registerCustomEvent(_UPDATE_EVENT_ID)
        _update_handler = _UpdateEventHandler()
        _custom_event.add(_update_handler)

        # Check for updates in the background
        updater.check_for_update(_notify_update_available)
    except Exception:
        app = adsk.core.Application.get()
        if app and app.userInterface:
            app.userInterface.messageBox(
                'Failed to start CloudCut Exporter:\n{}'.format(traceback.format_exc())
            )


def stop(context):
    """Called when the add-in is stopped."""
    try:
        # Unregister custom event
        global _custom_event, _update_handler
        app = adsk.core.Application.get()
        if _custom_event:
            app.unregisterCustomEvent(_UPDATE_EVENT_ID)
            _custom_event = None
            _update_handler = None

        commands.stop()
    except Exception:
        app = adsk.core.Application.get()
        if app and app.userInterface:
            app.userInterface.messageBox(
                'Failed to stop CloudCut Exporter:\n{}'.format(traceback.format_exc())
            )
