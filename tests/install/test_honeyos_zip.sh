#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

/bin/sh "$REPO_DIR/scripts/build_release_zip.sh" >/dev/null
ARCHIVE=$(find "$REPO_DIR/dist" -maxdepth 1 -name 'honeyos-*.zip' -print | sort | tail -n 1)
LISTING=$(unzip -Z1 "$ARCHIVE")

printf '%s\n' "$LISTING" | grep -q '/Install-HoneyOS.command$'
printf '%s\n' "$LISTING" | grep -q '/honeyos/__init__.py$'
printf '%s\n' "$LISTING" | grep -q '/scripts/install_honeyos.sh$'

if printf '%s\n' "$LISTING" | grep -Eq '/(tests|docs|\.git|\.venv|dist)/'; then
    echo "The user archive contains development or private files." >&2
    exit 1
fi

if printf '%s\n' "$LISTING" | grep -Eqi 'hermes|h2os|springbrand'; then
    echo "The user archive contains a legacy product path." >&2
    exit 1
fi
