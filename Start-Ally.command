#!/bin/bash
# Resolve the project from this file, including paths containing spaces or Chinese.
ALLY_PROJECT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ALLY_PYTHON="$ALLY_PROJECT_DIR/.venv/bin/python"
if [ ! -x "$ALLY_PYTHON" ]; then
    ALLY_PYTHON="$ALLY_PROJECT_DIR/.venv-mac/bin/python"
fi
if [ ! -x "$ALLY_PYTHON" ]; then
    printf '%s\n' '未找到项目 Python 环境。请先双击 Setup-Ally.command 完成安装。'
    read -r -p '按 Enter 关闭。' _
    exit 1
fi
"$ALLY_PYTHON" "$ALLY_PROJECT_DIR/scripts/start_ally.py" "$@"
ALLY_EXIT_CODE=$?
if [ "$ALLY_EXIT_CODE" -ne 0 ]; then
    read -r -p '按 Enter 关闭。' _
fi
exit "$ALLY_EXIT_CODE"
