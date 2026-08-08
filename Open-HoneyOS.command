#!/bin/sh
set -eu

REPO_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$REPO_DIR"

if [ ! -x ".venv/bin/honeyos" ]; then
    echo "HoneyOS 还没有安装，正在进入首次安装…"
    exec /bin/sh "$REPO_DIR/scripts/install_honeyos.sh"
fi

exec "$REPO_DIR/.venv/bin/honeyos" web
