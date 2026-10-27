"""CloudCut Exporter — Fusion 360 Add-in Entry Point.

Sends flat parts to CloudCut, or saves them as JSON/SVG, for CNC toolpath
generation. build.sh renames this file to match the add-in folder per build.
"""

import adsk.core
import adsk.fusion
import traceback
import os
import json

# Fusion loads each add-in as a package named after its folder, and all add-ins
# share one Python interpreter. Package-relative imports keep this add-in's
# modules (config, commands, lib) separate from another build's.
import importlib
from . import config

if config.DEV_RELOAD:
    importlib.reload(config)

# Only Direct builds self-update; the store zip doesn't ship lib/updater.py.
updater = None
if config.BUILD == 'direct':
    from .lib import updater
    # Apply any previously staged update before the commands are imported, so
    # this session runs the new code.
    if updater.apply_staged_update() or config.DEV_RELOAD:
        importlib.reload(config)
        importlib.reload(updater)

from . import commands

if config.DEV_RELOAD:
    importlib.reload(commands)

# Custom event for thread-safe UI messages (update downloaded, duplicate install)
_custom_event = None
_event_handler = None


class _MainThreadEventHandler(adsk.core.CustomEventHandler):
    """Shows messages on Fusion's main thread, after startup has finished."""
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            info = json.loads(args.additionalInfo)
            ui = adsk.core.Application.get().userInterface
            if info.get('kind') == 'update':
                ui.messageBox(
                    '{} v{} has been downloaded.\n\n'
                    'Please restart Fusion to apply the update.'.format(
                        config.PRODUCT_NAME, info.get('version', '?'))
                )
            elif info.get('kind') == 'duplicate':
                _mark_duplicate_warned()
                ui.messageBox(config.DUPLICATE_MESSAGE, config.DUPLICATE_TITLE)
        except Exception:
            pass


def _register_custom_event():
    global _custom_event, _event_handler
    if _custom_event:
        return
    app = adsk.core.Application.get()
    _custom_event = app.registerCustomEvent(config.CUSTOM_EVENT_ID)
    _event_handler = _MainThreadEventHandler()
    _custom_event.add(_event_handler)


def _fire(info):
    """Queue a message for the main thread. Safe to call from any thread."""
    try:
        app = adsk.core.Application.get()
        if app:
            app.fireCustomEvent(config.CUSTOM_EVENT_ID, json.dumps(info))
    except Exception:
        pass


def _notify_update_available(version):
    """Called from the updater's background thread."""
    _fire({'kind': 'update', 'version': version})


def _mark_duplicate_warned():
    try:
        os.makedirs(os.path.dirname(config.DUPLICATE_MARKER), exist_ok=True)
        open(config.DUPLICATE_MARKER, 'w').close()
    except Exception:
        pass


def _check_duplicate_install():
    """Warn (once ever) if the other build is loaded too.

    Whichever build loads second sees the other's command and shows the
    warning. Deferred through the custom event so it doesn't block startup.
    """
    ui = adsk.core.Application.get().userInterface
    if not ui.commandDefinitions.itemById(config.OTHER_BUILD_CMD_ID):
        return
    if os.path.exists(config.DUPLICATE_MARKER):
        return
    _register_custom_event()
    _fire({'kind': 'duplicate'})


def run(context):
    """Called when the add-in is started."""
    try:
        commands.start()

        if updater:
            _register_custom_event()
            # Check for updates in the background
            updater.check_for_update(_notify_update_available)

        _check_duplicate_install()
    except Exception:
        app = adsk.core.Application.get()
        if app and app.userInterface:
            app.userInterface.messageBox(
                'Failed to start {}:\n{}'.format(config.PRODUCT_NAME, traceback.format_exc())
            )


def stop(context):
    """Called when the add-in is stopped."""
    try:
        # Unregister custom event
        global _custom_event, _event_handler
        app = adsk.core.Application.get()
        if _custom_event:
            app.unregisterCustomEvent(config.CUSTOM_EVENT_ID)
            _custom_event = None
            _event_handler = None

        commands.stop()
    except Exception:
        app = adsk.core.Application.get()
        if app and app.userInterface:
            app.userInterface.messageBox(
                'Failed to stop {}:\n{}'.format(config.PRODUCT_NAME, traceback.format_exc())
            )
