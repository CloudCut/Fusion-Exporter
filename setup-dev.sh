#!/bin/bash
# Setup script: install FusionExporter as symlink (dev) or copy (testing).

ADDIN_DIR="$HOME/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns"
ADDIN_NAME="FusionExporter"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="$REPO_DIR/$ADDIN_NAME"
INSTALL_PATH="$ADDIN_DIR/$ADDIN_NAME"

echo "Fusion Exporter — Dev Setup"
echo "==========================="
echo ""
echo "Repo source: $SOURCE_DIR"
echo "Install to:  $INSTALL_PATH"
echo ""

# Check Fusion AddIns directory exists
if [ ! -d "$ADDIN_DIR" ]; then
    echo "ERROR: Fusion 360 AddIns directory not found:"
    echo "  $ADDIN_DIR"
    echo ""
    echo "Is Fusion 360 installed? The directory is created on first launch."
    exit 1
fi

# Show current state
if [ -L "$INSTALL_PATH" ]; then
    echo "Current install: SYMLINK -> $(readlink "$INSTALL_PATH")"
elif [ -d "$INSTALL_PATH" ]; then
    echo "Current install: COPY"
else
    echo "Current install: NONE"
fi
echo ""

# Ask what to install
echo "How would you like to install?"
echo "  1) Symlink (for development — changes in repo appear instantly)"
echo "  2) Copy (for testing — simulates what users have)"
echo "  3) Cancel"
echo ""
read -p "Choose [1/2/3]: " -n 1 -r
echo ""
echo ""

case $REPLY in
    1)
        MODE="symlink"
        ;;
    2)
        MODE="copy"
        ;;
    *)
        echo "Cancelled."
        exit 0
        ;;
esac

# Remove existing install
if [ -L "$INSTALL_PATH" ] || [ -d "$INSTALL_PATH" ]; then
    rm -rf "$INSTALL_PATH"
    echo "Removed existing install."
fi

if [ "$MODE" = "symlink" ]; then
    ln -s "$SOURCE_DIR" "$INSTALL_PATH"
    echo "Symlink created: $INSTALL_PATH -> $SOURCE_DIR"
else
    cp -R "$SOURCE_DIR" "$INSTALL_PATH"
    echo "Copied $ADDIN_NAME to AddIns directory."
fi

echo ""
echo "Done. Restart the add-in in Fusion (or restart Fusion) to pick up changes."
