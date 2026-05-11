#!/usr/bin/env bash
# Packages lambda/src/ into a zip that Terraform uploads to Lambda.
# Run from the repo root: bash rules-of-engagement/lambda/build.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/src"
DIST_DIR="$SCRIPT_DIR/dist"

mkdir -p "$DIST_DIR"

echo "Building Lambda package..."

# If requirements.txt has real packages, install them into the zip
# (currently empty — pure stdlib, so this is a no-op)
if grep -qvE '^\s*(#|$)' "$SRC_DIR/requirements.txt" 2>/dev/null; then
  echo "Installing pip dependencies..."
  pip install \
    --quiet \
    --target "$DIST_DIR/site-packages" \
    -r "$SRC_DIR/requirements.txt"
fi

# Create the zip
ZIP_PATH="$DIST_DIR/handler.zip"
rm -f "$ZIP_PATH"

# Add Lambda source files
(cd "$SRC_DIR" && zip -q -r "$ZIP_PATH" .)

# Add pip packages if any were installed
if [ -d "$DIST_DIR/site-packages" ]; then
  (cd "$DIST_DIR/site-packages" && zip -q -r "$ZIP_PATH" .)
fi

echo "Done: $ZIP_PATH ($(du -sh "$ZIP_PATH" | cut -f1))"
echo ""
echo "Next: run 'terraform apply' in rules-of-engagement/terraform/ to deploy."
