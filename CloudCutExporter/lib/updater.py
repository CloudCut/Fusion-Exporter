"""Auto-updater (Direct build only) — checks GitHub releases and stages updates for next restart.

Each release has the built Direct zip attached (CloudCut-direct-<ver>.zip, made
by build.sh). The store build never ships this file.
"""

import json
import os
import shutil
import threading

from .. import config

# GitHub repository to check for releases
GITHUB_OWNER = 'CloudCut'
GITHUB_REPO = 'Fusion-Exporter'

# Release asset to download: dist/CloudCut-direct-<ver>.zip from build.sh
ASSET_PREFIX = 'CloudCut-direct-'

ADDIN_DIR = config.ADDIN_DIR
STAGING_DIR = os.path.join(ADDIN_DIR, '_update_staging')
MANIFEST_FILE = os.path.join(ADDIN_DIR, config.ADDIN_NAME + '.manifest')
USER_AGENT = 'CloudCutExporter-Updater'


def _read_local_version():
    """Read the current version from the manifest file."""
    try:
        with open(MANIFEST_FILE, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        return manifest.get('version', '0.0.0')
    except Exception:
        return '0.0.0'


def _parse_version(version_str):
    """Parse a version string like '1.2.3' into a tuple of ints for comparison."""
    version_str = version_str.lstrip('vV')
    parts = []
    for p in version_str.split('.'):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _fetch_latest_release():
    """Query the GitHub API for the latest release. Returns (tag, asset_url) or None.

    Releases without a Direct zip attached are skipped (no update).
    """
    # Imported here, on the background thread, to keep add-in startup fast.
    from urllib.request import urlopen, Request

    url = 'https://api.github.com/repos/{}/{}/releases/latest'.format(
        GITHUB_OWNER, GITHUB_REPO)
    req = Request(url)
    req.add_header('Accept', 'application/vnd.github.v3+json')
    req.add_header('User-Agent', USER_AGENT)

    try:
        resp = urlopen(req, timeout=10)
        data = json.loads(resp.read().decode('utf-8'))
        tag = data.get('tag_name', '')
        for asset in data.get('assets', []):
            name = asset.get('name', '')
            if name.startswith(ASSET_PREFIX) and name.endswith('.zip'):
                asset_url = asset.get('browser_download_url', '')
                if tag and asset_url:
                    return tag, asset_url
    except Exception:
        pass
    return None


def _download_and_stage(asset_url):
    """Download the Direct zip and extract the add-in folder to the staging directory."""
    import tempfile
    import zipfile
    from urllib.request import urlopen, Request

    req = Request(asset_url)
    req.add_header('User-Agent', USER_AGENT)

    resp = urlopen(req, timeout=60)
    zip_data = resp.read()

    # Write to a temp file
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.zip')
    try:
        with os.fdopen(tmp_fd, 'wb') as f:
            f.write(zip_data)

        # Clean any previous staging
        if os.path.exists(STAGING_DIR):
            shutil.rmtree(STAGING_DIR)

        # The zip holds one top-level folder, the add-in itself
        # ("CloudCutExporter/..."); extract that folder's contents.
        staging_root = os.path.realpath(STAGING_DIR)
        with zipfile.ZipFile(tmp_path, 'r') as zf:
            prefix = config.ADDIN_NAME + '/'
            os.makedirs(STAGING_DIR, exist_ok=True)

            for member in zf.namelist():
                if not member.startswith(prefix):
                    continue

                relative = member[len(prefix):]
                if not relative:
                    continue

                dest = os.path.realpath(os.path.join(STAGING_DIR, relative))
                if not dest.startswith(staging_root + os.sep):
                    continue  # never write outside the staging folder
                if member.endswith('/'):
                    os.makedirs(dest, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(member) as src, open(dest, 'wb') as dst:
                        dst.write(src.read())

        # Only stage a complete add-in
        if not os.path.isfile(os.path.join(STAGING_DIR, config.ADDIN_NAME + '.manifest')):
            shutil.rmtree(STAGING_DIR)
            return False
        return True
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def apply_staged_update():
    """If a staged update exists, overwrite the add-in files with it.

    Call this at the very start of the add-in, BEFORE importing the commands.
    Returns True if an update was applied.
    """
    if not os.path.isdir(STAGING_DIR):
        return False

    try:
        # Copy staged files over the add-in directory
        for item in os.listdir(STAGING_DIR):
            src = os.path.join(STAGING_DIR, item)
            dst = os.path.join(ADDIN_DIR, item)

            # Skip the staging dir itself and hidden files
            if item.startswith('_update_') or item.startswith('.'):
                continue

            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

        # Clean up staging
        shutil.rmtree(STAGING_DIR)
        return True
    except Exception:
        # If something goes wrong, clean up staging so we don't loop on a bad update
        try:
            shutil.rmtree(STAGING_DIR)
        except Exception:
            pass
        return False


def check_for_update(notify_callback):
    """Check GitHub for a newer release in a background thread.

    Args:
        notify_callback: Called with (new_version_str,) from the background
                         thread if an update was downloaded and staged. It
                         should hand off to the main thread (custom event)
                         before showing anything.
    """
    def _worker():
        try:
            local_version = _parse_version(_read_local_version())
            result = _fetch_latest_release()
            if result is None:
                return

            tag, asset_url = result
            remote_version = _parse_version(tag)

            if remote_version <= local_version:
                return

            success = _download_and_stage(asset_url)
            if success and notify_callback:
                notify_callback(tag.lstrip('vV'))
        except Exception:
            pass  # Fail silently — update check should never break the add-in

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
