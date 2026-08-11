#!/bin/sh
set -eu

VERSION=0.3.1
REPOSITORY=Nicole202504/honeyos
ARCHIVE_URL="https://github.com/$REPOSITORY/archive/refs/heads/main.tar.gz"
INSTALL_ROOT="$HOME/.local/share/honeyos"
INSTALL_DIR="$INSTALL_ROOT/app"
STAGING_DIR="$INSTALL_ROOT/.app-new"
PREVIOUS_DIR="$INSTALL_ROOT/app.previous"
TEMP_DIR=$(mktemp -d)

cleanup() {
    rm -rf "$TEMP_DIR" "$STAGING_DIR"
}
trap cleanup EXIT HUP INT TERM

case "$INSTALL_ROOT" in
    "$HOME"/*) ;;
    *) echo "Refusing unsafe HoneyOS install path: $INSTALL_ROOT" >&2; exit 1 ;;
esac

for command_name in curl tar; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "HoneyOS needs $command_name to install from GitHub." >&2
        exit 1
    fi
done

for managed_path in "$INSTALL_DIR" "$STAGING_DIR" "$PREVIOUS_DIR"; do
    if [ -L "$managed_path" ]; then
        echo "Refusing to replace symlinked HoneyOS path: $managed_path" >&2
        exit 1
    fi
done

mkdir -p "$INSTALL_ROOT"
ARCHIVE="$TEMP_DIR/honeyos-$VERSION.tar.gz"
echo "Downloading HoneyOS v$VERSION from GitHub…"
curl -fsSL "$ARCHIVE_URL" -o "$ARCHIVE"

rm -rf "$STAGING_DIR"
mkdir "$STAGING_DIR"
tar -xzf "$ARCHIVE" -C "$STAGING_DIR" --strip-components=1
if [ ! -f "$STAGING_DIR/pyproject.toml" ] || [ ! -f "$STAGING_DIR/scripts/install_honeyos.sh" ]; then
    echo "The downloaded HoneyOS archive is incomplete." >&2
    exit 1
fi

rm -rf "$PREVIOUS_DIR"
if [ -d "$INSTALL_DIR" ]; then
    mv "$INSTALL_DIR" "$PREVIOUS_DIR"
    if [ -d "$PREVIOUS_DIR/.venv" ]; then
        mv "$PREVIOUS_DIR/.venv" "$STAGING_DIR/.venv"
    fi
fi
mv "$STAGING_DIR" "$INSTALL_DIR"

mkdir -p "$HOME/.local/bin"
ln -sfn "$INSTALL_DIR/.venv/bin/honeyos" "$HOME/.local/bin/honeyos"
PATH="$HOME/.local/bin:$PATH"
export PATH

if (exec </dev/tty) 2>/dev/null; then
    /bin/sh "$INSTALL_DIR/scripts/install_honeyos.sh" </dev/tty
else
    /bin/sh "$INSTALL_DIR/scripts/install_honeyos.sh"
fi

rm -rf "$PREVIOUS_DIR"
echo "HoneyOS command: $HOME/.local/bin/honeyos"
