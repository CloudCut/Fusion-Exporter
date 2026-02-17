#!/bin/bash
# One-time setup: create symlink from Fusion 360 AddIns directory to this repo.

ADDIN_DIR="$HOME/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns"
LINK_NAME="FusionExporter"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
LINK_PATH="$ADDIN_DIR/$LINK_NAME"

echo "Fusion Exporter — Development Setup"
echo "===================================="
echo ""
echo "Repo:   $REPO_DIR"
echo "Target: $LINK_PATH"
echo ""

# Check if AddIns directory exists
if [ ! -d "$ADDIN_DIR" ]; then
    echo "ERROR: Fusion 360 AddIns directory not found:"
    echo "  $ADDIN_DIR"
    echo ""
    echo "Is Fusion 360 installed? The directory is created on first launch."
    exit 1
fi

# Check if symlink already exists
if [ -L "$LINK_PATH" ]; then
    EXISTING_TARGET="$(readlink "$LINK_PATH")"
    if [ "$EXISTING_TARGET" = "$REPO_DIR" ]; then
        echo "Symlink already exists and points to the correct directory."
        echo "Nothing to do."
        exit 0
    else
        echo "WARNING: Symlink exists but points to a different location:"
        echo "  Current:  $EXISTING_TARGET"
        echo "  Expected: $REPO_DIR"
        echo ""
        read -p "Replace it? [y/N] " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm "$LINK_PATH"
        else
            echo "Aborted."
            exit 1
        fi
    fi
elif [ -e "$LINK_PATH" ]; then
    echo "ERROR: $LINK_PATH exists but is not a symlink."
    echo "Please remove it manually and run this script again."
    exit 1
fi

ln -s "$REPO_DIR" "$LINK_PATH"
echo "Symlink created successfully."
echo ""
echo "Next steps:"
echo "  1. Open Fusion 360"
echo "  2. Press Shift+S → Scripts and Add-Ins"
echo "  3. Switch to the Add-Ins tab"
echo "  4. Find 'FusionExporter' and click Run"
