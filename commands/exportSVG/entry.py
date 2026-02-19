"""Export SVG command — definition, dialog, and event handlers."""

import adsk.core
import adsk.fusion
import os
import traceback
import importlib

import config
from lib import utils, geometry_extractor, path_converter, svg_builder, json_builder

# Reload order matters: dependencies first
importlib.reload(config)
importlib.reload(utils)
importlib.reload(geometry_extractor)
importlib.reload(path_converter)
importlib.reload(svg_builder)
importlib.reload(json_builder)

# Globals for cleanup
_handlers = []
_button = None


def start():
    """Create the Export SVG command and add it to the toolbar."""
    app = adsk.core.Application.get()
    ui = app.userInterface

    cmd_def = ui.commandDefinitions.itemById(config.CMD_EXPORT_SVG_ID)
    if cmd_def:
        cmd_def.deleteMe()

    resource_dir = os.path.join(os.path.dirname(__file__), 'resources')

    cmd_def = ui.commandDefinitions.addButtonDefinition(
        config.CMD_EXPORT_SVG_ID,
        config.CMD_EXPORT_SVG_NAME,
        config.CMD_EXPORT_SVG_DESCRIPTION,
        resource_dir
    )

    on_created = CommandCreatedHandler()
    cmd_def.commandCreated.add(on_created)
    _handlers.append(on_created)

    # Add to toolbar
    workspace = ui.workspaces.itemById(config.WORKSPACE_ID)
    if workspace:
        tab = workspace.toolbarTabs.itemById(config.TAB_ID)
        if tab:
            panel = tab.toolbarPanels.itemById(config.PANEL_ID)
            if panel:
                global _button
                existing = panel.controls.itemById(config.CMD_EXPORT_SVG_ID)
                if existing:
                    existing.deleteMe()
                _button = panel.controls.addCommand(cmd_def)
                _button.isPromotedByDefault = False
                _button.isPromoted = False


def stop():
    """Remove the command from Fusion 360."""
    app = adsk.core.Application.get()
    ui = app.userInterface

    global _button
    if _button:
        _button.deleteMe()
        _button = None

    cmd_def = ui.commandDefinitions.itemById(config.CMD_EXPORT_SVG_ID)
    if cmd_def:
        cmd_def.deleteMe()

    _handlers.clear()


class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            cmd = adsk.core.Command.cast(args.command)
            inputs = cmd.commandInputs
            app = adsk.core.Application.get()
            design = adsk.fusion.Design.cast(app.activeProduct)

            if not design:
                app.userInterface.messageBox(
                    'No active Fusion 360 design.\n\n'
                    'Please open a design before exporting.'
                )
                return

            # Determine document units
            units_mgr = design.unitsManager
            default_length_unit = units_mgr.defaultLengthUnits
            is_metric = 'mm' in default_length_unit or 'cm' in default_length_unit or 'meter' in default_length_unit

            # Body selection input
            body_input = inputs.addSelectionInput(
                'bodySelection',
                'Bodies',
                'Select bodies to export'
            )
            body_input.addSelectionFilter('Bodies')
            body_input.setSelectionLimits(1, 0)  # min 1, no max

            # Pre-populate with currently selected bodies
            sel = app.userInterface.activeSelections
            for i in range(sel.count):
                entity = sel.item(i).entity
                if isinstance(entity, adsk.fusion.BRepBody):
                    body_input.addSelection(entity)

            # Units dropdown
            units_dropdown = inputs.addDropDownCommandInput(
                'outputUnits',
                'Output Units',
                adsk.core.DropDownStyles.TextListDropDownStyle
            )
            units_dropdown.listItems.add('Millimeters (mm)', is_metric, '')
            units_dropdown.listItems.add('Inches (in)', not is_metric, '')

            # Output format dropdown
            format_dropdown = inputs.addDropDownCommandInput(
                'outputFormat',
                'Output Format',
                adsk.core.DropDownStyles.TextListDropDownStyle
            )
            format_dropdown.listItems.add('SVG', True, '')
            format_dropdown.listItems.add('JSON', False, '')

            # Connect event handlers
            on_validate = ValidateInputsHandler()
            cmd.validateInputs.add(on_validate)
            _handlers.append(on_validate)

            on_execute = ExecuteHandler()
            cmd.execute.add(on_execute)
            _handlers.append(on_execute)

            on_destroy = DestroyHandler()
            cmd.destroy.add(on_destroy)
            _handlers.append(on_destroy)

        except Exception:
            app = adsk.core.Application.get()
            app.userInterface.messageBox(
                'Command creation failed:\n{}'.format(traceback.format_exc())
            )


class ValidateInputsHandler(adsk.core.ValidateInputsEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            inputs = args.inputs
            body_input = inputs.itemById('bodySelection')

            # Must have at least one body selected
            args.areInputsValid = body_input.selectionCount >= 1

        except Exception:
            args.areInputsValid = False


class ExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            app = adsk.core.Application.get()
            ui = app.userInterface
            design = adsk.fusion.Design.cast(app.activeProduct)
            inputs = args.command.commandInputs

            # Gather inputs
            body_input = inputs.itemById('bodySelection')
            units_dropdown = inputs.itemById('outputUnits')
            format_dropdown = inputs.itemById('outputFormat')

            bodies = []
            for i in range(body_input.selectionCount):
                entity = body_input.selection(i).entity
                if isinstance(entity, adsk.fusion.BRepBody):
                    bodies.append(entity)

            if not bodies:
                ui.messageBox('No bodies selected.')
                return

            # Determine output unit
            selected_unit = units_dropdown.selectedItem.name
            output_unit = 'mm' if 'mm' in selected_unit else 'in'

            # Determine output format
            export_format = 'json' if format_dropdown.selectedItem.name == 'JSON' else 'svg'
            file_ext = '.' + export_format
            format_label = export_format.upper()

            # Show file save dialog
            file_dialog = ui.createFileDialog()
            file_dialog.isMultiSelectEnabled = False
            if export_format == 'json':
                file_dialog.title = 'Save JSON File'
                file_dialog.filter = 'JSON Files (*.json)'
            else:
                file_dialog.title = 'Save SVG File'
                file_dialog.filter = 'SVG Files (*.svg)'

            # Default filename from design name
            doc_name = app.activeDocument.name if app.activeDocument else 'export'
            file_dialog.initialFilename = doc_name + file_ext

            result = file_dialog.showSave()
            if result != adsk.core.DialogResults.DialogOK:
                return

            file_path = file_dialog.filename
            if not file_path.lower().endswith(file_ext):
                file_path += file_ext

            utils.log('Starting {} export...'.format(format_label))
            utils.log('Bodies: {}'.format(len(bodies)))
            utils.log('Output unit: {}'.format(output_unit))

            # Write debug report next to the SVG file
            debug_path = os.path.splitext(file_path)[0] + '_debug.txt'
            try:
                geometry_extractor.dump_debug_report(bodies, debug_path)
            except Exception:
                utils.log('Warning: debug report failed: {}'.format(
                    traceback.format_exc()))

            # Extract geometry (material thickness auto-detected per body)
            components = geometry_extractor.extract_from_bodies(bodies)

            if not components:
                ui.messageBox(
                    'No exportable geometry found.\n\n'
                    'The exporter looks for planar faces on the selected bodies. '
                    'Make sure your design contains extruded flat parts.\n\n'
                    'A debug report was saved to:\n{}'.format(debug_path)
                )
                return

            # Build output
            if export_format == 'json':
                content = json_builder.build_json(components, output_unit)
            else:
                content = svg_builder.build_svg(components, output_unit)

            # Write file
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
            except (IOError, OSError) as e:
                ui.messageBox(
                    'Failed to write {} file:\n{}\n\n'
                    'Check file permissions and path.'.format(format_label, str(e))
                )
                return

            # Summary
            total_ops = sum(
                len(comp.operations) for comp in components
            )
            total_paths = sum(
                len(op.contours) for comp in components for op in comp.operations
            )

            utils.log('Export complete: {}'.format(file_path))
            ui.messageBox(
                '{} exported successfully!\n\n'
                'File: {}\n'
                'Components: {}\n'
                'Operations: {}\n'
                'Paths: {}\n\n'
                'Debug report: {}'.format(
                    format_label, file_path, len(components), total_ops,
                    total_paths, debug_path
                )
            )

        except Exception:
            app = adsk.core.Application.get()
            err_msg = traceback.format_exc()
            # Try to mention debug report path if we got that far
            extra = ''
            try:
                if debug_path:
                    extra = '\n\nDebug report: {}'.format(debug_path)
            except NameError:
                pass
            app.userInterface.messageBox(
                'Export failed:\n{}{}'.format(err_msg, extra)
            )


class DestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        # Clean up command-specific resources if needed
        pass
