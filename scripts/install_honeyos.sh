#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

case "$(uname -s)" in
    Darwin|Linux) ;;
    *)
        echo "HoneyOS currently supports macOS and Linux." >&2
        exit 1
        ;;
esac

if ! command -v uv >/dev/null 2>&1; then
    if ! command -v curl >/dev/null 2>&1; then
        echo "HoneyOS needs curl to install its runtime automatically." >&2
        exit 1
    fi
    echo "Installing the HoneyOS runtime…"
    UV_INSTALL_DIR=${UV_INSTALL_DIR:-"${HOME}/.local/bin"}
    export UV_INSTALL_DIR
    mkdir -p "$UV_INSTALL_DIR"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    PATH="$UV_INSTALL_DIR:${HOME}/.local/bin:${HOME}/.cargo/bin:$PATH"
    export PATH
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "HoneyOS could not install uv automatically." >&2
    exit 1
fi

cd "$REPO_DIR"
echo "Preparing HoneyOS…"
uv sync --quiet --extra honeyos
exec uv run honeyos setup
