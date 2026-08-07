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

if printf '%s\n' "$LISTING" | grep -Eq '^[^/]+/(tests|docs|\.git|\.venv|dist)/'; then
    echo "The user archive contains development or private files." >&2
    exit 1
fi

if printf '%s\n' "$LISTING" | grep -Eqi 'hermes|h2os|springbrand'; then
    echo "The user archive contains a legacy product path." >&2
    exit 1
fi

TEMP_ROOT=$(mktemp -d)
trap 'rm -rf "$TEMP_ROOT"' EXIT HUP INT TERM
unzip -q "$ARCHIVE" -d "$TEMP_ROOT"
EXTRACTED=$(find "$TEMP_ROOT" -mindepth 1 -maxdepth 1 -type d -name 'honeyos-*' -print | head -n 1)
TEST_HOME="$TEMP_ROOT/home"
mkdir -p "$TEST_HOME/.hermes"
printf 'untouched\n' > "$TEST_HOME/.hermes/marker"

HOME="$TEST_HOME" uv sync --project "$EXTRACTED" --locked --extra honeyos --quiet
HOME="$TEST_HOME" uv run --project "$EXTRACTED" honeyos init >/dev/null

test -f "$TEST_HOME/.honeyos/config.yaml"
test "$(cat "$TEST_HOME/.hermes/marker")" = "untouched"
