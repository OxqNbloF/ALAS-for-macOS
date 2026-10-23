#!/bin/bash
# 生成并校验依赖锁，供首次安装复现完全相同的依赖图。
#   Runtime/locks/conda-osx-arm64.lock    Conda 显式锁（URL + SHA256，安装时不再求解）
#   Runtime/locks/requirements.lock.txt   pip 哈希锁（--require-hashes，安装时不再解析）
# 默认会创建临时环境完整验证一遍；--no-verify 只生成并做快速解析检查。
set -euo pipefail
cd "$(dirname "$0")/.."

ROOT="${ALAS_RUNTIME_ROOT:-$HOME/Library/Application Support/AzurLaneAutoScript}"
RUNTIME="$PWD/ALAS for macOS/Runtime"
LOCKS="$RUNTIME/locks"
MAMBA="${ALAS_LOCK_MAMBA:-$ROOT/bin/micromamba}"
PYTHON="${ALAS_LOCK_PYTHON:-$ROOT/bootstrap/bin/python}"
VERIFY=1
case "${1:-}" in
    "") ;;
    --no-verify) VERIFY=0 ;;
    *) echo "用法：$0 [--no-verify]" >&2; exit 2 ;;
esac

[[ -x "$MAMBA" ]] || { echo "缺少环境管理器：$MAMBA" >&2; echo "可设置 ALAS_LOCK_MAMBA 指向 micromamba。" >&2; exit 1; }
[[ -x "$PYTHON" ]] || { echo "缺少 Python：$PYTHON" >&2; echo "可设置 ALAS_LOCK_PYTHON 指向带 PyYAML 的 Python。" >&2; exit 1; }

STAGING="$(mktemp -d /private/tmp/alas-lock.XXXXXX)"
trap 'rm -rf "$STAGING"' EXIT
mkdir -p "$STAGING/pip" "$STAGING/home/.conda" "$LOCKS"
# 隔离 HOME，避免写入用户的 ~/.conda 或 pip 缓存。
export HOME="$STAGING/home"
export MAMBA_ROOT_PREFIX="$STAGING/mamba" CONDA_PKGS_DIRS="$STAGING/pkgs"
export PIP_DISABLE_PIP_VERSION_CHECK=1

echo "== 解析 Conda 依赖 =="
"$PYTHON" - "$RUNTIME" "$STAGING/spec.yml" "$STAGING/requirements.txt" <<'PY'
import sys
from pathlib import Path
import yaml
sys.path.insert(0, sys.argv[1])
import runtime
spec, requirements = runtime.specification(Path(sys.argv[1]))
Path(sys.argv[2]).write_text(yaml.safe_dump(spec))
Path(sys.argv[3]).write_text("\n".join(requirements) + "\n")
print(f"Conda 直接依赖 {len(spec['dependencies'])} 个，pip 依赖 {len(requirements)} 个")
PY

"$MAMBA" --no-rc create --dry-run --json -y -p "$STAGING/env" \
    --override-channels -f "$STAGING/spec.yml" > "$STAGING/resolve.json"
"$PYTHON" - "$STAGING/resolve.json" "$STAGING/conda.lock" <<'PY'
import json
import sys
from pathlib import Path
actions = json.loads(Path(sys.argv[1]).read_text())["actions"]
# LINK 与 FETCH 在 dry-run 中会重复列出同一批包，按文件名去重。
records = {record["fn"]: record for record in actions.get("LINK", [])}
records.update({record["fn"]: record for record in actions.get("FETCH", [])})
if not records:
    raise SystemExit("求解结果为空，无法生成锁")
for record in records.values():
    if not record.get("url") or not record.get("sha256"):
        raise SystemExit(f"缺少 URL 或 SHA256：{record.get('fn')}")
ordered = sorted(records.values(), key=lambda r: r["fn"])
# 头部记录包数量与总字节数，供安装界面估算下载百分比。
total_size = sum(int(record.get("size") or 0) for record in ordered)
lines = [
    "# 由 scripts/lock-dependencies.sh 从 Runtime/environment.macos-arm64.yml 生成。",
    "# 目标平台：macOS arm64。请勿手工编辑。",
    f"# package-count: {len(ordered)}",
    f"# total-size: {total_size}",
    "@EXPLICIT",
]
lines += [f"{record['url']}#{record['sha256']}" for record in ordered]
Path(sys.argv[2]).write_text("\n".join(lines) + "\n")
print(f"Conda 锁：{len(records)} 个包")
PY

echo "== 校验 Conda 锁可解析 =="
"$MAMBA" --no-rc create --dry-run -y -p "$STAGING/lock-check" -f "$STAGING/conda.lock" >/dev/null

echo "== 下载 pip 构建产物 =="
"$PYTHON" -m pip download --no-deps --dest "$STAGING/pip" \
    --python-version 3.8 --platform macosx_11_0_arm64 --implementation cp --abi cp38 \
    -r "$STAGING/requirements.txt" 2>&1 | tail -3
"$PYTHON" - "$STAGING/pip" "$STAGING/requirements.txt" "$STAGING/pip.lock" <<'PY'
import hashlib
import re
import sys
from pathlib import Path

def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()

requirements = [line.strip() for line in Path(sys.argv[2]).read_text().splitlines() if line.strip()]
artifacts = [path for path in Path(sys.argv[1]).iterdir() if path.is_file()]
index = {path.name.lower(): path for path in artifacts}

lines = ["# 由 scripts/lock-dependencies.sh 生成；目标：CPython 3.8 / macOS arm64。",
         "# 安装：pip install --require-hashes -r requirements.lock.txt", ""]
missing = []
for requirement in requirements:
    name, _, version = requirement.partition("==")
    if not version:
        raise SystemExit(f"需求未固定版本：{requirement}")
    variants = {name.lower(), name.lower().replace("-", "_"),
                name.lower().replace("-", "."), canonical(name)}
    candidates = [path for filename, path in index.items()
                  if any(filename.startswith(variant + "-" + version) for variant in variants)]
    if len(candidates) != 1:
        missing.append(f"{requirement} -> {[path.name for path in candidates]}")
        continue
    digest = hashlib.sha256(candidates[0].read_bytes()).hexdigest()
    lines.append(f"{name}=={version} --hash=sha256:{digest}")
if missing:
    raise SystemExit("无法唯一匹配构建产物：\n" + "\n".join(missing))
Path(sys.argv[3]).write_text("\n".join(lines) + "\n")
print(f"pip 锁：{len(requirements)} 个包，{len(artifacts)} 个构建产物")
PY

if [[ "$VERIFY" = 1 ]]; then
    echo "== 完整验证：按锁创建环境并安装依赖 =="
    "$MAMBA" --no-rc create -y -p "$STAGING/verify" -f "$STAGING/conda.lock"
    "$STAGING/verify/bin/python" -m pip install --no-index --find-links "$STAGING/pip" \
        --require-hashes -r "$STAGING/pip.lock"
    "$STAGING/verify/bin/python" -m pip check
    echo "验证通过：Conda 显式锁 + pip 哈希锁可从离线产物完整安装"
else
    echo "== 已跳过完整验证（--no-verify）=="
fi

cp "$STAGING/conda.lock" "$LOCKS/conda-osx-arm64.lock"
cp "$STAGING/pip.lock" "$LOCKS/requirements.lock.txt"
echo
echo "已写入：$LOCKS"
/usr/bin/du -sh "$LOCKS"
echo "锁内容参与环境指纹，重新构建后首次安装将使用固定的依赖图。"
