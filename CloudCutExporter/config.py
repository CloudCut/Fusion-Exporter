"""Global constants for the CloudCut Exporter add-in."""

import json
import os

# Which build this is. The repo source is the Direct build; build.sh rewrites
# this line to 'store' for the Autodesk App Store zip.
#   'direct' = "CloudCut Direct", downloaded straight from CloudCut; self-updates
#              from GitHub releases.
#   'store'  = "CloudCut", from the Autodesk App Store; no updater (the store
#              owns installs and updates, and lib/updater.py isn't shipped).
BUILD = 'direct'

COMPANY_NAME = 'CloudCut'
ADDIN_DIR = os.path.dirname(os.path.abspath(__file__))

# Per-build identity. Folder name, command ID and custom event ID all differ so
# both builds can be installed side by side. Direct keeps the original
# CloudCutExporter names so existing installs upgrade in place.
_BUILDS = {
    'direct': {
        'addin_name': 'CloudCutExporter',
        'product_name': 'CloudCut Direct',
        'cmd_id': 'cloudCutExportSVGCommandId',
        'cmd_name': 'Send to CloudCut (Direct)',
        'event_id': 'CloudCutExporterUpdateEvent',
        'source_app': 'fusion-direct',
    },
    'store': {
        'addin_name': 'CloudCut',
        'product_name': 'CloudCut',
        'cmd_id': 'cloudCutStoreSendCommandId',
        'cmd_name': 'Send to CloudCut',
        'event_id': 'CloudCutStoreEvent',
        'source_app': 'fusion',
    },
}
_this = _BUILDS[BUILD]
_other = _BUILDS['store' if BUILD == 'direct' else 'direct']

ADDIN_NAME = _this['addin_name']
PRODUCT_NAME = _this['product_name']
SOURCE_APP = _this['source_app']   # source.app tag on handoffs
CUSTOM_EVENT_ID = _this['event_id']
OTHER_BUILD_CMD_ID = _other['cmd_id']

# Read version from manifest
_manifest_path = os.path.join(ADDIN_DIR, ADDIN_NAME + '.manifest')
try:
    with open(_manifest_path, 'r', encoding='utf-8') as _f:
        VERSION = json.load(_f).get('version', '0.0.0')
except Exception:
    VERSION = '0.0.0'

# CloudCut API that "Send to CloudCut" posts exports to. Set the
# CLOUDCUT_API_URL environment variable to test against a local workshop.
CLOUDCUT_API_URL = os.environ.get('CLOUDCUT_API_URL', 'https://shop.cloudcut.cam').rstrip('/')

# Dev convenience: set CLOUDCUT_DEV=1 to hot-reload modules on add-in restart.
DEV_RELOAD = bool(os.environ.get('CLOUDCUT_DEV'))

# Privacy policy, linked from the dialog's Privacy tab. A copy ships in
# docs/privacy.html, linked from the help page (regenerate with
# tools/fetch_privacy_policy.py). Help is shown from the dialog's help button.
PRIVACY_URL = 'https://cloudcut.cam/privacy-policy/'

# Links on the dialog's About tab
WEBSITE_URL = 'https://cloudcut.cam'
WORKSHOP_URL = 'https://shop.cloudcut.cam'
HELP_FILE = os.path.join(ADDIN_DIR, 'docs', 'help.html')

# Command identifiers
CMD_EXPORT_SVG_ID = _this['cmd_id']
CMD_EXPORT_SVG_NAME = _this['cmd_name']
CMD_EXPORT_SVG_DESCRIPTION = '{} v{}: send flat parts to CloudCut for CNC toolpath generation'.format(
    PRODUCT_NAME, VERSION)

# Shown once if both builds are loaded at the same time.
DUPLICATE_TITLE = 'CloudCut is installed twice'
DUPLICATE_MESSAGE = (
    'You have two versions of Send to CloudCut installed:\n\n'
    '• CloudCut, from the Autodesk App Store\n'
    '• CloudCut Direct, downloaded straight from CloudCut, which updates itself\n\n'
    'You only need one. Turn the other off in Utilities > Add-ins.'
)
# Shared by both builds so the warning shows once in total, not once per build.
DUPLICATE_MARKER = os.path.join(
    os.environ.get('APPDATA') or os.path.expanduser('~/Library/Application Support'),
    'CloudCut', 'fusion-duplicate-warned')

# Toolbar placements (workspace, tab, panel)
TOOLBAR_PLACEMENTS = [
    ('FusionSolidEnvironment', 'SolidTab',  'SolidCreatePanel'),    # Design toolbar
    ('FusionSolidEnvironment', 'ToolsTab',  'SolidScriptsAddinsPanel'),  # Design > Utilities tab
    ('CAMEnvironment',         'CAMActionTab', 'CAMActionPanel'),   # Manufacture toolbar
]
