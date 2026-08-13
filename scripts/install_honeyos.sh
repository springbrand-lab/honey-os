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

UV_VERSION=0.11.21
UV_INSTALL_DIR=${UV_INSTALL_DIR:-"${HOME}/.local/share/honeyos/runtime"}
UV_BIN="$UV_INSTALL_DIR/uv"
UV_CURRENT_VERSION=$("$UV_BIN" --version 2>/dev/null || :)

case "$UV_CURRENT_VERSION" in
    "uv $UV_VERSION"|"uv $UV_VERSION "*) ;;
    *)
        if ! command -v curl >/dev/null 2>&1; then
            echo "HoneyOS needs curl to install its runtime automatically." >&2
            exit 1
        fi
        echo "Installing the HoneyOS runtime…"
        export UV_INSTALL_DIR
        UV_NO_MODIFY_PATH=1
        export UV_NO_MODIFY_PATH
        mkdir -p "$UV_INSTALL_DIR"
        curl -LsSf "https://releases.astral.sh/github/uv/releases/download/$UV_VERSION/uv-installer.sh" | sh
        ;;
esac

case "$("$UV_BIN" --version 2>/dev/null || :)" in
    "uv $UV_VERSION"|"uv $UV_VERSION "*) ;;
    *) echo "HoneyOS could not install its private uv $UV_VERSION runtime." >&2; exit 1 ;;
esac

cd "$REPO_DIR"
echo "Preparing HoneyOS…"
"$UV_BIN" sync --locked --quiet --extra honeyos --extra mcp

mkdir -p "$HOME/.local/bin"
ln -sfn "$REPO_DIR/.venv/bin/honeyos" "$HOME/.local/bin/honeyos"

HONEYOS_DATA_HOME=${HONEYOS_HOME:-"${HOME}/.honeyos"}

if [ -f "$HONEYOS_DATA_HOME/config.yaml" ]; then
    echo "发现已有的 HoneyOS 和伴侣数据，正在安全升级…"
    echo "✓ 人设、关系记忆与历史聊天会保留"
    echo "✓ 模型、飞书和微信配置会继续使用"
    exec "$UV_BIN" run honeyos web
fi

if (exec </dev/tty) 2>/dev/null; then
    exec "$UV_BIN" run honeyos setup </dev/tty
fi
exec "$UV_BIN" run honeyos setup
