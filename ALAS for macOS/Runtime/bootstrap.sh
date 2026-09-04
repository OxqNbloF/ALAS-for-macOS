#!/bin/bash
# 准备私有部署工具，不加载 Shell 配置或调用系统包管理器。
set -euo pipefail
MODE="${1:?mode required}"
ROOT="${2:?private runtime directory required}"
RESOURCES="$(cd "$(dirname "$0")" && pwd)"
[[ "$ROOT" = /* && "$ROOT" != / ]] || exit 2
case "$ROOT/" in
    *.app/*) echo '运行数据必须位于 App 外的独立目录。'; exit 2 ;;
esac
# 写入前检查真实目录
ANCESTOR="$ROOT"
while [[ ! -d "$ANCESTOR" ]]; do ANCESTOR="$(dirname "$ANCESTOR")"; done
PHYSICAL="$(cd "$ANCESTOR" && pwd -P)"
case "$(printf '%s' "$PHYSICAL/" | /usr/bin/tr '[:upper:]' '[:lower:]')" in
    *.app/*) echo '运行数据必须位于 App 外的独立目录。'; exit 2 ;;
esac
[[ "$(uname -m)" = arm64 ]] || { echo '此运行环境需要 Apple Silicon Mac。'; exit 2; }
umask 077
mkdir -p "$ROOT/bin" "$ROOT/cache" "$ROOT/tmp" "$ROOT/home"
export HOME="$ROOT/home"
export MAMBA_ROOT_PREFIX="$ROOT/mamba" CONDA_PKGS_DIRS="$ROOT/cache/conda"
export XDG_CACHE_HOME="$ROOT/cache" XDG_CONFIG_HOME="$ROOT/home/.config"
export PIP_CACHE_DIR="$ROOT/cache/pip" PIP_CONFIG_FILE=/dev/null
export PYTHONNOUSERSITE=1 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
export TMPDIR="$ROOT/tmp" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
export PATH="$ROOT/bootstrap/bin:/usr/bin:/bin:/usr/sbin:/sbin"
unset PYTHONPATH PYTHONHOME CONDA_PREFIX VIRTUAL_ENV PIP_INDEX_URL PIP_EXTRA_INDEX_URL
# 已安装环境不再下载工具；启动、更新或回退时缺失工具则报错。
if [[ -f "$ROOT/active.json" || -f "$ROOT/environment.json" ]]; then
    [[ -f "$ROOT/bootstrap/.complete" && -x "$ROOT/bootstrap/bin/python" && -x "$ROOT/bootstrap/bin/git" ]] || {
        echo '已保存的私有工具环境损坏，请恢复备份；不会自动重建环境。'; exit 1;
    }
    exec "$ROOT/bootstrap/bin/python" "$RESOURCES/runtime.py" "$MODE" "$ROOT"
fi
[[ "$MODE" = prepare ]] || { echo '请先完成首次环境配置。'; exit 1; }
echo '@@ALAS_STAGE:1:下载并校验环境管理器' 
MAMBA="$ROOT/bin/micromamba"
# 保留旧失败文件并重新下载
if [[ -f "$MAMBA" ]] && ! "$MAMBA" --version; then
    REJECTED="$(mktemp -d "$ROOT/bin/rejected.XXXXXX")"
    /bin/mv "$MAMBA" "$REJECTED/micromamba"
    echo '旧环境管理器无法执行，已保留原件；将重新下载并校验。'
fi
if [[ ! -x "$MAMBA" ]]; then
    echo '下载并校验 ARM64 环境管理器…'
    DOWNLOAD="$(mktemp "$ROOT/tmp/micromamba.XXXXXX")"
    /usr/bin/curl --fail --location --proto '=https' --tlsv1.2 --retry 2 --retry-all-errors \
        --connect-timeout 20 --max-time 300 \
        https://mirror.nju.edu.cn/anaconda/cloud/conda-forge/osx-arm64/micromamba-2.3.2-0.tar.bz2 -o "$DOWNLOAD"
    SHA="$(/usr/bin/shasum -a 256 "$DOWNLOAD")"
    [[ "${SHA%% *}" = ae0b50b441fef93abd20711f18b074359a7f8f1f523a8046a4d6ab44aa68ff1b ]] || {
        echo '环境管理器校验失败，停止安装。'; exit 1;
    }
    /usr/bin/tar -xjf "$DOWNLOAD" -C "$ROOT" bin/micromamba
    chmod 700 "$MAMBA"
    /bin/rm "$DOWNLOAD"
fi
echo '@@ALAS_STAGE:2:安装私有 Python 和 Git'
if [[ ! -f "$ROOT/bootstrap/.complete" ]]; then
    echo '安装应用私有 Python 和 Git…'
    "$MAMBA" --no-rc create -y -p "$ROOT/bootstrap" --override-channels \
        -c https://mirror.nju.edu.cn/anaconda/cloud/conda-forge python=3.11 pyyaml git
    touch "$ROOT/bootstrap/.complete"
fi
exec "$ROOT/bootstrap/bin/python" "$RESOURCES/runtime.py" "$MODE" "$ROOT"
