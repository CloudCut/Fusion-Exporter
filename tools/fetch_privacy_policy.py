"""Regenerate CloudCutExporter/docs/privacy.html from https://cloudcut.cam/privacy-policy/.

The Autodesk App Store wants the privacy policy inside the app, not just a
link, so the add-in bundles a copy. Run this whenever the policy changes:

    python3 tools/fetch_privacy_policy.py
"""

import html
import os
import re
import sys
from urllib.request import Request, urlopen

URL = 'https://cloudcut.cam/privacy-policy/'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                   'CloudCutExporter', 'docs', 'privacy.html')

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CloudCut Privacy Policy</title>
<style>
  :root {{ color-scheme: light dark; --fg: #1d1d1f; --muted: #6e6e73; --bg: #ffffff; --accent: #0a66c2; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --fg: #f2f2f7; --muted: #a1a1a6; --bg: #1c1c1e; --accent: #5aa9ff; }}
  }}
  body {{ margin: 0; background: var(--bg); color: var(--fg);
         font: 14px/1.55 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }}
  main {{ max-width: 720px; margin: 0 auto; padding: 24px 20px 48px; }}
  h1 {{ font-size: 24px; margin: 0 0 4px; }}
  h2 {{ font-size: 17px; margin: 28px 0 8px; }}
  .updated, .source {{ color: var(--muted); font-size: 13px; margin: 0; }}
  .source {{ margin: 6px 0 20px; }}
  a {{ color: var(--accent); }}
  ul {{ padding-left: 20px; }}
  li {{ margin: 4px 0; }}
</style>
</head>
<body>
<main>
<h1>{title}</h1>
<p class="updated">{updated}</p>
<p class="source">A copy of <a href="{url}">{url}</a>, included with the add-in. The online version is authoritative.</p>
{body}
</main>
</body>
</html>
"""


def main():
    req = Request(URL, headers={'User-Agent': 'Mozilla/5.0 (CloudCut privacy fetch)'})
    page = urlopen(req, timeout=30).read().decode('utf-8')

    title = re.search(r'<h1[^>]*>(.*?)</h1>', page, re.S).group(1).strip()
    updated = re.search(r'<p class="updated">(.*?)</p>', page, re.S).group(1).strip()
    body = re.search(r'<article[^>]*>(.*?)</article>', page, re.S).group(1)

    # Keep the structural tags, drop classes/ids and anything scripted
    body = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', body, flags=re.S)
    body = re.sub(r'<(\w+)\s+(?!href)[^>]*>', r'<\1>', body)
    body = re.sub(r'\n\s*\n+', '\n', body).strip()
    if 'cloudcutapp@' not in body:
        sys.exit('Unexpected page layout; privacy.html not written.')

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(PAGE.format(title=title, updated=updated, url=html.escape(URL), body=body))
    print('Wrote {} ({})'.format(os.path.normpath(OUT), updated))


if __name__ == '__main__':
    main()
