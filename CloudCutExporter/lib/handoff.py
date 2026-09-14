"""Send to CloudCut — hand exported JSON to the CloudCut shop.

The exporter POSTs every thickness group in one request (no sign-in) and gets
back a shop link. Opening that link in the browser lets the signed-in user
claim the files, which become one job per thickness.
"""

import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import config


class SendError(Exception):
    """A user-facing reason the send didn't go through."""


def send_handoff(files):
    """POST files ([{'name', 'content'}]) to CloudCut; return the shop URL to open."""
    payload = {
        'source': {'app': 'fusion', 'version': config.VERSION},
        'files': files,
    }
    req = Request(
        config.CLOUDCUT_API_URL + '/v1/handoffs',
        data=json.dumps(payload).encode('utf-8'),
        method='POST',
    )
    req.add_header('Content-Type', 'application/json')
    req.add_header('User-Agent', 'CloudCutExporter/{}'.format(config.VERSION))

    try:
        with urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode('utf-8'))
    except HTTPError as e:
        if e.code == 429:
            raise SendError('Too many exports were sent from this network recently. '
                            'Wait a few minutes and try again.')
        detail = ''
        try:
            detail = json.loads(e.read().decode('utf-8')).get('error', '')
        except Exception:
            pass
        raise SendError("CloudCut couldn't accept the export (HTTP {}{}).".format(
            e.code, ': ' + detail if detail else ''))
    except (URLError, OSError, ValueError) as e:
        raise SendError("Couldn't reach CloudCut ({}). Check your internet connection.".format(
            getattr(e, 'reason', e)))

    url = body.get('url') if isinstance(body, dict) else None
    if not url:
        raise SendError('CloudCut sent back an unexpected response.')
    return url
