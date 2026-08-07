#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
VERSION=$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$REPO_DIR/pyproject.toml" | head -n 1)

if [ -z "$VERSION" ]; then
    echo "Could not read the HoneyOS version." >&2
    exit 1
fi

DIST_DIR="$REPO_DIR/dist"
ARCHIVE="$DIST_DIR/honeyos-$VERSION.zip"
CHECKSUM="$ARCHIVE.sha256"
mkdir -p "$DIST_DIR"

git -C "$REPO_DIR" archive \
    --format=zip \
    --prefix="honeyos-$VERSION/" \
    --output="$ARCHIVE" \
    HEAD

if command -v shasum >/dev/null 2>&1; then
    (cd "$DIST_DIR" && shasum -a 256 "${ARCHIVE##*/}") > "$CHECKSUM"
elif command -v sha256sum >/dev/null 2>&1; then
    (cd "$DIST_DIR" && sha256sum "${ARCHIVE##*/}") > "$CHECKSUM"
else
    echo "A SHA-256 checksum utility is required." >&2
    exit 1
fi

echo "$ARCHIVE"
echo "$CHECKSUM"
