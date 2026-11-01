"""Command registry — start and stop all registered commands."""

import importlib

if __package__ == 'commands':
    # A pre-1.5 add-in just applied this update and reloaded it in place, as
    # top-level modules. This code only runs as a package (relative imports),
    # so ask for a restart instead of failing; the new files are already on disk.
    def start():
        import adsk.core
        adsk.core.Application.get().userInterface.messageBox(
            'Send to CloudCut has been updated.\n\n'
            'Please restart Fusion to finish the update.',
            'CloudCut'
        )

    def stop():
        pass

else:
    from .. import config
    from .exportSVG import entry as exportSVG_entry

    if config.DEV_RELOAD:
        importlib.reload(exportSVG_entry)

    def start():
        """Register all commands with Fusion 360."""
        exportSVG_entry.start()

    def stop():
        """Remove all commands from Fusion 360."""
        exportSVG_entry.stop()
