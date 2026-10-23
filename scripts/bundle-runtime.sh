#!/bin/bash
# 从已部署的运行数据生成 App 内置运行时种子。
# 生成物位于 "ALAS for macOS/Runtime/bundled/"，构建时随 Runtime 复制进 App；
# 首次部署优先使用这些组件，缺失或损坏时运行时代码会自动回退到在线安装。
set -euo pipefail
cd "$(dirname "$0")/.."

ROOT="${ALAS_RUNTIME_ROOT:-$HOME/Library/Application Support/AzurLaneAutoScript}"
BUNDLE="$PWD/ALAS for macOS/Runtime/bundled"
RUNTIME="$PWD/ALAS for macOS/Runtime"
ADB_ARCHIVE="platform-tools_r37.0.1-darwin.zip"
ADB_SHA256="ee39ad5967e95c2a07f04dbcbde96b1a0c916ba376096db5d2f498b7727a5d1d"
ADB_URL="https://mirrors.cloud.tencent.com/AndroidSDK/$ADB_ARCHIVE"

TOOLCHAIN_ONLY=0
case "${1:-}" in
    "") ;;
    --toolchain-only) TOOLCHAIN_ONLY=1 ;;
    *) echo "用法：$0 [--toolchain-only]" >&2; exit 2 ;;
esac

[[ -f "$ROOT/active.json" ]] || {
    echo "未找到已部署的运行数据：$ROOT" >&2
    echo "请先在 App 中完成一次部署，或用 ALAS_RUNTIME_ROOT 指定部署目录。" >&2
    exit 1
}
[[ -x "$ROOT/bin/micromamba" ]] || { echo "缺少环境管理器：$ROOT/bin/micromamba" >&2; exit 1; }
[[ -x "$ROOT/bootstrap/bin/git" ]] || { echo "缺少私有 Git：$ROOT/bootstrap/bin/git" >&2; exit 1; }
[[ -x "$ROOT/bootstrap/bin/python" ]] || { echo "缺少私有 Python：$ROOT/bootstrap/bin/python" >&2; exit 1; }

STAGING="$(mktemp -d /private/tmp/alas-bundle.XXXXXX)"
trap 'rm -rf "$STAGING"' EXIT
mkdir -p "$BUNDLE"

record() {
    /usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' \
        "$ROOT/active.json" "$1"
}

echo "== 环境管理器 =="
/bin/cp "$ROOT/bin/micromamba" "$BUNDLE/micromamba"
chmod 700 "$BUNDLE/micromamba"
"$BUNDLE/micromamba" --version

echo "== ADB =="
if [[ -f "$ROOT/tmp/$ADB_ARCHIVE" ]]; then
    /bin/cp "$ROOT/tmp/$ADB_ARCHIVE" "$BUNDLE/$ADB_ARCHIVE"
else
    /usr/bin/curl --fail --location --proto '=https' --tlsv1.2 --retry 2 --retry-all-errors \
        --connect-timeout 20 --max-time 300 "$ADB_URL" -o "$BUNDLE/$ADB_ARCHIVE"
fi
[[ "$(/usr/bin/shasum -a 256 "$BUNDLE/$ADB_ARCHIVE" | /usr/bin/awk '{print $1}')" = "$ADB_SHA256" ]] || {
    echo "ADB 安装包 SHA256 校验失败，已移除。" >&2
    /bin/rm -f "$BUNDLE/$ADB_ARCHIVE"
    exit 1
}

echo "== 核心快照 =="
CORE="$(record repository)"
[[ -f "$CORE/.git/HEAD" && -f "$CORE/gui.py" ]] || { echo "核心不是有效的 Git 工作树：$CORE" >&2; exit 1; }
if ! "$ROOT/bootstrap/bin/git" -C "$CORE" rev-parse --verify refs/heads/master >/dev/null 2>&1; then
    echo "核心不在 master 分支，请先在 App 的「核心更新」页同步一次后再执行。" >&2
    exit 1
fi
/bin/rm -f "$BUNDLE/core.bundle"
"$ROOT/bootstrap/bin/git" -C "$CORE" bundle create "$BUNDLE/core.bundle" HEAD refs/heads/master
echo "核心提交：$("$ROOT/bootstrap/bin/git" -C "$CORE" rev-parse --short HEAD)"

if [[ "$TOOLCHAIN_ONLY" = 1 ]]; then
    echo "== 已跳过依赖缓存（--toolchain-only）=="
else
    export MAMBA_ROOT_PREFIX="$ROOT/mamba"
    export CONDA_PKGS_DIRS="$ROOT/cache/conda"

    echo "== Conda 包缓存 =="
    SPEC="$STAGING/spec.yml"
    REQUIREMENTS="$STAGING/requirements.txt"
    "$ROOT/bootstrap/bin/python" - "$CORE" "$RUNTIME" "$SPEC" "$REQUIREMENTS" <<'PY'
import sys
from pathlib import Path
import yaml
sys.path.insert(0, sys.argv[2])
import runtime
spec, requirements = runtime.specification(Path(sys.argv[1]))
Path(sys.argv[3]).write_text(yaml.safe_dump(spec))
Path(sys.argv[4]).write_text("\n".join(requirements) + "\n")
PY

    PKGS="$ROOT/cache/conda"
    CONDALOCK="$RUNTIME/locks/conda-osx-arm64.lock"
    if ! /usr/bin/find "$PKGS" -maxdepth 1 \( -name '*.conda' -o -name '*.tar.bz2' \) -print -quit 2>/dev/null | grep -q .; then
        echo "本地包缓存不可用，按锁下载固定版本的依赖包…"
        if [[ -f "$CONDALOCK" ]]; then
            "$ROOT/bin/micromamba" --no-rc create --download-only -y -p "$STAGING/env" -f "$CONDALOCK"
        else
            "$ROOT/bin/micromamba" --no-rc create --download-only -y -p "$STAGING/env" \
                --override-channels -f "$SPEC"
        fi
        /bin/rm -rf "$STAGING/env"
    fi

    /bin/rm -rf "$BUNDLE/conda-pkgs"
    mkdir -p "$BUNDLE/conda-pkgs"
    if /usr/bin/find "$PKGS" -maxdepth 1 \( -name '*.conda' -o -name '*.tar.bz2' \) -print -quit 2>/dev/null | grep -q .; then
        /usr/bin/find "$PKGS" -maxdepth 1 \( -name '*.conda' -o -name '*.tar.bz2' \) \
            -exec /bin/cp {} "$BUNDLE/conda-pkgs/" \;
        touch "$BUNDLE/conda-pkgs/.complete"
    else
        echo "警告：没有可用的 Conda 包，离线安装将回退在线镜像。" >&2
        /bin/rm -rf "$BUNDLE/conda-pkgs"
    fi

    echo "== 仓库索引 =="
    /bin/rm -rf "$BUNDLE/mamba"
    if [[ -d "$ROOT/mamba/pkgs/cache" ]] && /usr/bin/find "$ROOT/mamba/pkgs/cache" -name '*.json' -print -quit | grep -q .; then
        mkdir -p "$BUNDLE/mamba/pkgs"
        /bin/cp -R "$ROOT/mamba/pkgs/cache" "$BUNDLE/mamba/pkgs/cache"
    else
        echo "警告：没有仓库索引缓存，Conda 将只能在线解析。" >&2
    fi

    echo "== Python 依赖 =="
    PIPLOCK="$RUNTIME/locks/requirements.lock.txt"
    ENV_PYTHON="$(record environment)/bin/python"
    /bin/rm -rf "$BUNDLE/wheels"
    mkdir -p "$BUNDLE/wheels"
    if [[ -f "$PIPLOCK" ]]; then
        # 锁是按 CPython 3.8 / arm64 生成的，用交叉下载获取完全相同的构建产物。
        if ! "$ROOT/bootstrap/bin/python" -m pip download --no-deps --disable-pip-version-check \
                --dest "$BUNDLE/wheels" --python-version 3.8 --platform macosx_11_0_arm64 \
                --implementation cp --abi cp38 -r "$PIPLOCK"; then
            echo "警告：部分锁定依赖未能下载，离线安装可能回退在线镜像。" >&2
        fi
    elif [[ -x "$ENV_PYTHON" ]]; then
        if ! "$ENV_PYTHON" -m pip download --disable-pip-version-check \
                --dest "$BUNDLE/wheels" -r "$REQUIREMENTS"; then
            echo "警告：部分 Python 依赖未能下载，离线安装可能回退在线镜像。" >&2
        fi
    else
        echo "警告：未找到锁或已安装环境，跳过 Python 依赖。" >&2
    fi
    if [[ -z "$(/usr/bin/find "$BUNDLE/wheels" -type f -print -quit)" ]]; then
        /bin/rm -rf "$BUNDLE/wheels"
    fi
fi

echo
echo "内置运行时种子：$BUNDLE"
/usr/bin/du -sh "$BUNDLE"
echo "重新构建 App 后生效；发布包会包含上述文件。"
