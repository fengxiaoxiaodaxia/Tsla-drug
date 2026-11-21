#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN=${PYTHON:-python3}
VENV_PYTHON="$ROOT/.venv/bin/python"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "未找到 $PYTHON_BIN，请先安装 Python 3.10 或更高版本。" >&2
    exit 1
fi

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
    echo "需要 Python 3.10 或更高版本。" >&2
    exit 1
fi

if [ ! -x "$VENV_PYTHON" ]; then
    "$PYTHON_BIN" -m venv "$ROOT/.venv"
fi

"$VENV_PYTHON" -m pip install -r "$ROOT/app/requirements.txt"

printf '\n依赖安装完成。管理服务：\n'
printf '  %s start --ip <热点接口IPv4>\n' "$ROOT/fsd-mitm"
printf '  %s status\n' "$ROOT/fsd-mitm"
printf '  %s stop\n' "$ROOT/fsd-mitm"
