"""Auto-updater — checks GitHub releases and stages updates for next restart."""

import json
import os
import shutil
import tempfile
import threading
import zipfile

try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError
except ImportError:
    from urllib2 import urlopen, Request, URLError

# GitHub repository to check for releases
GITHUB_OWNER = 'CloudCut'
GITHUB_REPO = 'Fusion-Exporter'

ADDIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGING_DIR = os.path.join(ADDIN_DIR, '_update_staging')
MANIFEST_FILE = os.path.join(ADDIN_DIR, 'CloudCutExporter.manifest')


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
    """Query the GitHub API for the latest release. Returns (tag, zipball_url) or None."""
    url = 'https://api.github.com/repos/{}/{}/releases/latest'.format(
        GITHUB_OWNER, GITHUB_REPO)
    req = Request(url)
    req.add_header('Accept', 'application/vnd.github.v3+json')
    req.add_header('User-Agent', 'CloudCutExporter-Updater')

    try:
        resp = urlopen(req, timeout=10)
        data = json.loads(resp.read().decode('utf-8'))
        tag = data.get('tag_name', '')
        zipball_url = data.get('zipball_url', '')
        if tag and zipball_url:
            return tag, zipball_url
    except Exception:
        pass
    return None


def _download_and_stage(zipball_url):
    """Download a release zipball and extract it to the staging directory."""
    req = Request(zipball_url)
    req.add_header('User-Agent', 'CloudCutExporter-Updater')

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

        # Extract — GitHub zipballs have a top-level directory like "owner-repo-sha/"
        # The add-in lives in the "CloudCutExporter/" subfolder of the repo,
        # so we only extract that subfolder's contents.
        with zipfile.ZipFile(tmp_path, 'r') as zf:
            names = zf.namelist()
            # Find the GitHub top-level prefix (e.g. "CloudCut-Fusion-Exporter-abc1234/")
            top_prefix = ''
            if names:
                first = names[0]
                if '/' in first:
                    top_prefix = first.split('/')[0] + '/'

            # The add-in subfolder within the repo
            addin_prefix = top_prefix + 'CloudCutExporter/'

            os.makedirs(STAGING_DIR, exist_ok=True)

            for member in names:
                # Only extract files inside the CloudCutExporter/ subfolder
                if not member.startswith(addin_prefix):
                    continue

                relative = member[len(addin_prefix):]
                if not relative:
                    continue

                dest = os.path.join(STAGING_DIR, relative)
                if member.endswith('/'):
                    os.makedirs(dest, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(member) as src, open(dest, 'wb') as dst:
                        dst.write(src.read())

        return True
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def apply_staged_update():
    """If a staged update exists, overwrite the add-in files with it.

    Call this at the very start of run(), BEFORE importing any other add-in modules.
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
        notify_callback: Called with (new_version_str,) on the main thread if an
                         update was downloaded and staged. The callback should show
                         a message telling the user to restart Fusion.
    """
    def _worker():
        try:
            local_version = _parse_version(_read_local_version())
            result = _fetch_latest_release()
            if result is None:
                return

            tag, zipball_url = result
            remote_version = _parse_version(tag)

            if remote_version <= local_version:
                return

            success = _download_and_stage(zipball_url)
            if success and notify_callback:
                notify_callback(tag.lstrip('vV'))
        except Exception:
            pass  # Fail silently — update check should never break the add-in

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
