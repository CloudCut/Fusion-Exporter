#!/bin/bash
# Build both add-in zips from CloudCutExporter/:
#   dist/CloudCut-store-<ver>.zip   Autodesk App Store upload. Folder "CloudCut",
#                                   BUILD='store', no lib/updater.py.
#   dist/CloudCut-direct-<ver>.zip  Attach to the GitHub release; Direct installs
#                                   update themselves from it. Folder "CloudCutExporter".
# Neither zip contains __pycache__, .DS_Store, .vscode or update staging.
#
# Release: ./build.sh && gh release create v<ver> dist/CloudCut-direct-<ver>.zip
set -euo pipefail
cd "$(dirname "$0")"

# First python3 on PATH that actually runs (skips broken framework installs)
for PYTHON in $(which -a python3) /usr/bin/python3; do "$PYTHON" -c '' 2>/dev/null && break; done

SRC=CloudCutExporter
VERSION=$("$PYTHON" -c "import json;print(json.load(open('$SRC/$SRC.manifest'))['version'])")
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
mkdir -p dist

build() {
    local build=$1 folder=$2 manifest_id=$3
    local dir="$STAGE/$build/$folder"
    local excludes=(--exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store'
                    --exclude '.vscode' --exclude '_update_staging')
    [ "$build" = store ] && excludes+=(--exclude 'lib/updater.py')
    mkdir -p "$dir"
    rsync -a "${excludes[@]}" "$SRC/" "$dir/"

    # Fusion needs <folder>/<folder>.py and <folder>.manifest
    if [ "$folder" != "$SRC" ]; then
        mv "$dir/$SRC.py" "$dir/$folder.py"
        mv "$dir/$SRC.manifest" "$dir/$folder.manifest"
    fi

    "$PYTHON" - "$dir" "$folder" "$build" "$manifest_id" <<'PY'
import json, re, sys
d, folder, build, manifest_id = sys.argv[1:]
p = d + '/config.py'
s = open(p).read()
s2 = re.sub(r"^BUILD = '.*'$", "BUILD = '{}'".format(build), s, count=1, flags=re.M)
assert re.search(r"^BUILD = '{}'$".format(build), s2, re.M), 'BUILD line not found'
open(p, 'w').write(s2)

p = '{}/{}.manifest'.format(d, folder)
m = json.load(open(p))
m['id'] = manifest_id
open(p, 'w').write(json.dumps(m, indent=4) + '\n')
PY

    "$PYTHON" -m py_compile $(find "$dir" -name '*.py') && find "$dir" -name '__pycache__' -prune -exec rm -rf {} +

    local out="dist/CloudCut-$build-$VERSION.zip"
    rm -f "$out"
    (cd "$STAGE/$build" && zip -qrX - "$folder") > "$out"
    echo "Built $out"
}

build store  CloudCut         com.cloudcut.exporter.store
build direct CloudCutExporter com.cloudcut.exporter

# Sanity checks
if unzip -l "dist/CloudCut-store-$VERSION.zip" | grep -q 'updater.py'; then
    echo "ERROR: store zip contains updater.py" >&2; exit 1
fi
for z in dist/CloudCut-*-"$VERSION".zip; do
    if unzip -l "$z" | grep -Eq '__pycache__|\.DS_Store|\.vscode|_update_staging'; then
        echo "ERROR: $z contains dev files" >&2; exit 1
    fi
done
echo "OK"
