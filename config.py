"""Global constants for the FusionExporter add-in."""

ADDIN_NAME = 'FusionExporter'
COMPANY_NAME = ''

# Command identifiers
CMD_EXPORT_SVG_ID = 'exportSVGCommandId'
CMD_EXPORT_SVG_NAME = 'Export SVG'
CMD_EXPORT_SVG_DESCRIPTION = 'Export design geometry as a CNC-compatible SVG file'

# Toolbar placements (workspace, tab, panel)
TOOLBAR_PLACEMENTS = [
    ('FusionSolidEnvironment', 'SolidTab',  'SolidCreatePanel'),    # Design toolbar
    ('FusionSolidEnvironment', 'ToolsTab',  'SolidScriptsAddinsPanel'),  # Design > Utilities tab
    ('CAMEnvironment',         'CAMActionTab', 'CAMActionPanel'),   # Manufacture toolbar
]
