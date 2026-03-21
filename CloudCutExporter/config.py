"""Global constants for the FusionExporter add-in."""

import json
import os

ADDIN_NAME = 'FusionExporter'
COMPANY_NAME = ''

# Read version from manifest
_manifest_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'FusionExporter.manifest')
try:
    with open(_manifest_path, 'r', encoding='utf-8') as _f:
        VERSION = json.load(_f).get('version', '0.0.0')
except Exception:
    VERSION = '0.0.0'

# Command identifiers
CMD_EXPORT_SVG_ID = 'exportSVGCommandId'
CMD_EXPORT_SVG_NAME = 'Export SVG v{}'.format(VERSION)
CMD_EXPORT_SVG_DESCRIPTION = 'Export design geometry as a CNC-compatible SVG file'

# Toolbar placements (workspace, tab, panel)
TOOLBAR_PLACEMENTS = [
    ('FusionSolidEnvironment', 'SolidTab',  'SolidCreatePanel'),    # Design toolbar
    ('FusionSolidEnvironment', 'ToolsTab',  'SolidScriptsAddinsPanel'),  # Design > Utilities tab
    ('CAMEnvironment',         'CAMActionTab', 'CAMActionPanel'),   # Manufacture toolbar
]
