#!/bin/bash
# 运行 Python 单元测试、离线 Git 集成测试和 Xcode 单元测试
# 依赖安装到 build/test-venv
set -euo pipefail
cd "$(dirname "$0")/.."

VENV="${ALAS_TEST_VENV:-$PWD/build/test-venv}"
if [[ ! -x "$VENV/bin/python" ]]; then
    echo "创建测试虚拟环境：$VENV"
    python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt

echo "== Python 单元测试 =="
"$VENV/bin/python" -B -m unittest discover -s Tests -p 'test_*.py'

echo "== 离线 Git 更新/回退集成测试 =="
"$VENV/bin/python" -B Tests/integration_git_updates.py

if [[ "${ALAS_SKIP_XCODE_TESTS:-0}" == "1" ]]; then
    echo "== Swift 测试：已按 ALAS_SKIP_XCODE_TESTS=1 跳过 =="
    exit 0
fi

echo "== Swift 单元测试 =="
if [[ -z "${DEVELOPER_DIR:-}" ]]; then
    export DEVELOPER_DIR="$(xcode-select -p)"
fi
xcodebuild -project 'ALAS for macOS.xcodeproj' -scheme 'ALAS for macOS' \
    -destination 'platform=macOS,arch=arm64' -configuration Debug \
    -derivedDataPath build/DerivedData test

echo "全部测试通过"
