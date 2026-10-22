#!/bin/bash
# Bootstrap a verified uv binary; Python and Node stay inside this project.
set -euo pipefail
ALLY_PROJECT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
ALLY_TOOLS="$ALLY_PROJECT_DIR/.ally-tools"
ALLY_MANIFEST="$ALLY_PROJECT_DIR/scripts/runtime-downloads.json"
ALLY_STAGE=''
finish() {
    ALLY_STATUS=$?
    if [ -n "$ALLY_STAGE" ]; then rm -rf -- "$ALLY_STAGE"; fi
    if [ "$ALLY_STATUS" -ne 0 ]; then
        printf '\n%s\n' '安装未完成。请检查上方提示和网络，再次双击 Setup-Ally.command。'
    fi
    if [ -t 0 ]; then read -r -p '按 Enter 关闭窗口。' _ || true; fi
    exit "$ALLY_STATUS"
}
trap finish EXIT
if [ "$(uname -s)" != 'Darwin' ]; then
    printf '%s\n' '此安装入口用于 Mac。Windows 请使用 Setup-Ally.cmd。'
    exit 1
fi
case "$(uname -m)" in
    arm64) ALLY_PLATFORM='mac-arm64' ;;
    x86_64) ALLY_PLATFORM='mac-x64' ;;
    *) printf '%s\n' '不支持此 Mac 处理器。'; exit 1 ;;
esac
ALLY_UV_VERSION="$(plutil -extract uv_version raw -o - "$ALLY_MANIFEST")"
ALLY_PYTHON_VERSION="$(plutil -extract python_version raw -o - "$ALLY_MANIFEST")"
mkdir -p "$ALLY_TOOLS"
ALLY_UV="$ALLY_TOOLS/uv/uv"
if [ ! -x "$ALLY_UV" ] || [ "$("$ALLY_UV" --version 2>/dev/null | awk '{print $2}' || true)" != "$ALLY_UV_VERSION" ]; then
    printf '%s\n' '正在准备安装工具（首次需要联网）……'
    ALLY_STAGE="$(mktemp -d "$ALLY_TOOLS/.uv-stage.XXXXXX")"
    ALLY_URL="$(plutil -extract "platforms.$ALLY_PLATFORM.uv.url" raw -o - "$ALLY_MANIFEST")"
    ALLY_HASH="$(plutil -extract "platforms.$ALLY_PLATFORM.uv.sha256" raw -o - "$ALLY_MANIFEST")"
    curl --proto '=https' --tlsv1.2 -fL --retry 3 --connect-timeout 30 \
        "$ALLY_URL" -o "$ALLY_STAGE/uv.tar.gz"
    ALLY_ACTUAL="$(shasum -a 256 "$ALLY_STAGE/uv.tar.gz")"
    if [ "${ALLY_ACTUAL%% *}" != "$ALLY_HASH" ]; then
        printf '%s\n' 'SHA256 校验失败，已停止安装。'; exit 1
    fi
    tar -xzf "$ALLY_STAGE/uv.tar.gz" -C "$ALLY_STAGE"
    ALLY_UV_DIRS=("$ALLY_STAGE"/uv-*)
    if [ "${#ALLY_UV_DIRS[@]}" -ne 1 ] || [ ! -x "${ALLY_UV_DIRS[0]}/uv" ]; then
        printf '%s\n' '安装工具压缩包不完整。'; exit 1
    fi
    if [ -d "$ALLY_TOOLS/uv" ]; then mv "$ALLY_TOOLS/uv" "$ALLY_STAGE/previous"; fi
    if ! mv "${ALLY_UV_DIRS[0]}" "$ALLY_TOOLS/uv"; then
        if [ -d "$ALLY_STAGE/previous" ]; then mv "$ALLY_STAGE/previous" "$ALLY_TOOLS/uv"; fi
        exit 1
    fi
fi
export UV_PYTHON_INSTALL_DIR="$ALLY_TOOLS/python"
export UV_PYTHON_BIN_DIR="$ALLY_TOOLS/python-bin"
export UV_CACHE_DIR="$ALLY_TOOLS/cache"
export UV_NO_MODIFY_PATH=1 UV_PYTHON_INSTALL_BIN=0 UV_PYTHON_INSTALL_REGISTRY=0
export PYTHONUTF8=1 PYTHONUNBUFFERED=1
unset VIRTUAL_ENV PYTHONHOME PYTHONPATH UV_PROJECT_ENVIRONMENT
cd "$ALLY_PROJECT_DIR"
"$ALLY_UV" run --no-project --no-config --managed-python --python "$ALLY_PYTHON_VERSION" \
    "$ALLY_PROJECT_DIR/scripts/setup_ally.py" "$@"
