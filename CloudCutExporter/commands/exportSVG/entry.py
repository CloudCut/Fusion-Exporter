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
_buttons = []


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

    # Add to all configured toolbar locations
    for workspace_id, tab_id, panel_id in config.TOOLBAR_PLACEMENTS:
        workspace = ui.workspaces.itemById(workspace_id)
        if not workspace:
            continue
        tab = workspace.toolbarTabs.itemById(tab_id)
        if not tab:
            continue
        panel = tab.toolbarPanels.itemById(panel_id)
        if not panel:
            continue
        existing = panel.controls.itemById(config.CMD_EXPORT_SVG_ID)
        if existing:
            existing.deleteMe()
        button = panel.controls.addCommand(cmd_def)
        button.isPromotedByDefault = True
        button.isPromoted = True
        _buttons.append(button)


def stop():
    """Remove the command from Fusion 360."""
    app = adsk.core.Application.get()
    ui = app.userInterface

    for button in _buttons:
        try:
            button.deleteMe()
        except Exception:
            pass
    _buttons.clear()

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

            # Filter section label
            inputs.addTextBoxCommandInput(
                'filterLabel', '', '<b>Filter export by:</b>', 1, True
            )

            # Appearance filter dropdown
            root = design.rootComponent
            appearance_names = set()
            for body in root.bRepBodies:
                appearance_names.add(body.appearance.name)
            for occ in root.allOccurrences:
                for body in occ.bRepBodies:
                    appearance_names.add(body.appearance.name)

            appearance_dropdown = inputs.addDropDownCommandInput(
                'appearanceFilter',
                'Appearances',
                adsk.core.DropDownStyles.CheckBoxDropDownStyle
            )
            appearance_dropdown.listItems.add('All', True, '')
            for name in sorted(appearance_names):
                appearance_dropdown.listItems.add(name, True, '')

            # Thickness filter dropdown (populated dynamically when bodies are selected)
            thickness_dropdown = inputs.addDropDownCommandInput(
                'thicknessFilter',
                'Thicknesses',
                adsk.core.DropDownStyles.CheckBoxDropDownStyle
            )

            # Pre-populate if bodies are already selected
            _rebuild_thickness_dropdown(thickness_dropdown, body_input)

            # Connect event handlers
            on_input_changed = InputChangedHandler()
            cmd.inputChanged.add(on_input_changed)
            _handlers.append(on_input_changed)
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


def _rebuild_thickness_dropdown(thickness_dropdown, body_input):
    """Rebuild the thickness checkbox dropdown from the currently selected bodies."""
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)

    # Determine display unit from the units dropdown
    inputs = thickness_dropdown.parentCommandInput or None
    output_unit = 'in'
    try:
        units_dropdown = thickness_dropdown.commandInputs.itemById('outputUnits')
        if units_dropdown and 'mm' in units_dropdown.selectedItem.name:
            output_unit = 'mm'
    except Exception:
        # Fall back to design units
        if design:
            default_unit = design.unitsManager.defaultLengthUnits
            if 'mm' in default_unit or 'cm' in default_unit or 'meter' in default_unit:
                output_unit = 'mm'

    # Clear existing items
    items = thickness_dropdown.listItems
    for i in range(items.count - 1, -1, -1):
        items.item(i).deleteMe()

    # Gather selected bodies
    bodies = []
    for i in range(body_input.selectionCount):
        entity = body_input.selection(i).entity
        if isinstance(entity, adsk.fusion.BRepBody):
            bodies.append(entity)

    if not bodies:
        return

    # Compute unique thicknesses
    thicknesses = set()
    for body in bodies:
        t = geometry_extractor.get_body_thickness(body)
        if t is None:
            t = 0.0
        thicknesses.add(round(t, 4))

    # Add "All" + individual thicknesses, all checked
    if len(thicknesses) > 1:
        thickness_dropdown.listItems.add('All', True, '')
    for t_cm in sorted(thicknesses):
        if output_unit == 'mm':
            label = '{:.2f} mm'.format(t_cm * 10)
        else:
            label = '{:.4f} in'.format(t_cm / 2.54)
        thickness_dropdown.listItems.add(label, True, '')


_prev_all_state = {}  # dropdown id -> bool


def _handle_all_toggle(dropdown):
    """Handle 'All' checkbox toggle logic for a CheckBoxDropDown."""
    items = dropdown.listItems
    if items.count < 2:
        return

    all_item = items.item(0)
    if all_item.name != 'All':
        return

    individual_items = [items.item(i) for i in range(1, items.count)]
    prev_all = _prev_all_state.get(dropdown.id, True)
    curr_all = all_item.isSelected

    if curr_all != prev_all:
        # User toggled "All" — apply to all individuals
        for item in individual_items:
            item.isSelected = curr_all
    else:
        # User toggled an individual — sync "All" to match
        all_item.isSelected = all(
            item.isSelected for item in individual_items
        )

    _prev_all_state[dropdown.id] = all_item.isSelected


class InputChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            changed_input = args.input
            inputs = args.inputs

            if changed_input.id == 'bodySelection':
                # Rebuild thickness dropdown when body selection changes
                thickness_dropdown = inputs.itemById('thicknessFilter')
                body_input = inputs.itemById('bodySelection')
                if thickness_dropdown and body_input:
                    _rebuild_thickness_dropdown(thickness_dropdown, body_input)
                return

            if changed_input.id in ('appearanceFilter', 'thicknessFilter'):
                _handle_all_toggle(changed_input)

        except Exception:
            pass


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

            # Filter bodies by appearance
            appearance_dropdown = inputs.itemById('appearanceFilter')
            checked_appearances = set()
            items = appearance_dropdown.listItems
            for i in range(1, items.count):  # skip "All"
                if items.item(i).isSelected:
                    checked_appearances.add(items.item(i).name)

            bodies = [b for b in bodies if b.appearance.name in checked_appearances]

            if not bodies:
                ui.messageBox('No bodies match the selected appearances.')
                return

            # Determine output unit
            selected_unit = units_dropdown.selectedItem.name
            output_unit = 'mm' if 'mm' in selected_unit else 'in'

            # Read checked thicknesses from the dropdown
            thickness_dropdown = inputs.itemById('thicknessFilter')
            checked_labels = set()
            t_items = thickness_dropdown.listItems
            for i in range(t_items.count):
                item = t_items.item(i)
                if item.name != 'All' and item.isSelected:
                    checked_labels.add(item.name)

            # Group bodies by thickness
            thickness_groups = {}  # label -> list of bodies
            for body in bodies:
                t = geometry_extractor.get_body_thickness(body)
                if t is None:
                    t = 0.0
                t_rounded = round(t, 4)
                if output_unit == 'mm':
                    label = '{:.2f} mm'.format(t_rounded * 10)
                else:
                    label = '{:.4f} in'.format(t_rounded / 2.54)
                thickness_groups.setdefault(label, []).append(body)

            # Keep only groups whose label is checked
            export_groups = {
                label: group for label, group in thickness_groups.items()
                if label in checked_labels
            }

            if not export_groups:
                ui.messageBox('No bodies match the selected thicknesses.')
                return

            # Determine output format
            export_format = 'json' if format_dropdown.selectedItem.name == 'JSON' else 'svg'
            file_ext = '.' + export_format
            format_label = export_format.upper()

            # Show file save dialog (user picks base filename)
            file_dialog = ui.createFileDialog()
            file_dialog.isMultiSelectEnabled = False
            if export_format == 'json':
                file_dialog.title = 'Save JSON File'
                file_dialog.filter = 'JSON Files (*.json)'
            else:
                file_dialog.title = 'Save SVG File'
                file_dialog.filter = 'SVG Files (*.svg)'

            doc_name = app.activeDocument.name if app.activeDocument else 'export'
            file_dialog.initialFilename = doc_name + file_ext

            result = file_dialog.showSave()
            if result != adsk.core.DialogResults.DialogOK:
                return

            base_path = file_dialog.filename
            if base_path.lower().endswith(file_ext):
                base_path = base_path[:-len(file_ext)]

            # Export one file per thickness group
            exported_files = []
            all_debug_path = base_path + '_debug.txt'

            for label, group_bodies in sorted(export_groups.items()):
                # Build filename: base_0.75in.svg or base_19.05mm.svg
                thickness_tag = label.replace(' ', '')
                file_path = '{}_{}{}'.format(base_path, thickness_tag, file_ext)

                utils.log('Starting {} export for thickness {}...'.format(
                    format_label, label))
                utils.log('Bodies: {}'.format(len(group_bodies)))
                utils.log('Output unit: {}'.format(output_unit))

                # Write debug report (once, for all bodies)
                if not exported_files:
                    try:
                        all_bodies = []
                        for g in export_groups.values():
                            all_bodies.extend(g)
                        geometry_extractor.dump_debug_report(
                            all_bodies, all_debug_path)
                    except Exception:
                        utils.log('Warning: debug report failed: {}'.format(
                            traceback.format_exc()))

                # Extract geometry
                components = geometry_extractor.extract_from_bodies(group_bodies)

                if not components:
                    utils.log('No exportable geometry for thickness {}, '
                              'skipping.'.format(label))
                    continue

                # Build output
                if export_format == 'json':
                    content = json_builder.build_json(components, output_unit)
                else:
                    content = svg_builder.build_svg(components, output_unit)

                # Write file
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    exported_files.append((file_path, len(components)))
                except (IOError, OSError) as e:
                    ui.messageBox(
                        'Failed to write {} file:\n{}\n\n'
                        'Check file permissions and path.'.format(
                            format_label, str(e))
                    )

            if not exported_files:
                ui.messageBox(
                    'No exportable geometry found.\n\n'
                    'The exporter looks for planar faces on the selected bodies. '
                    'Make sure your design contains extruded flat parts.\n\n'
                    'A debug report was saved to:\n{}'.format(all_debug_path)
                )
                return

            # Summary
            summary_lines = ['{} exported successfully!\n'.format(format_label)]
            for fp, comp_count in exported_files:
                summary_lines.append('  {} ({} components)'.format(
                    os.path.basename(fp), comp_count))
            summary_lines.append('\nDebug report: {}'.format(all_debug_path))

            utils.log('Export complete: {} file(s)'.format(len(exported_files)))
            ui.messageBox('\n'.join(summary_lines))

        except Exception:
            app = adsk.core.Application.get()
            err_msg = traceback.format_exc()
            # Try to mention debug report path if we got that far
            extra = ''
            try:
                if all_debug_path:
                    extra = '\n\nDebug report: {}'.format(all_debug_path)
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
