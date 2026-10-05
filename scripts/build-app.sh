#!/bin/bash
set -euo pipefail
# 构建 Release App，使用无需证书的 ad-hoc 签名并校验。
cd "$(dirname "$0")/.."
if [[ -z "${DEVELOPER_DIR:-}" ]]; then
    export DEVELOPER_DIR="$(xcode-select -p)"
fi
if [[ ! -x "$DEVELOPER_DIR/usr/bin/xcodebuild" ]]; then
    echo '错误：需要完整 Xcode。请通过 DEVELOPER_DIR 指定 Xcode.app/Contents/Developer。' >&2
    exit 1
fi
BUILD="$(mktemp -d /private/tmp/alas-release.XXXXXX)"
trap 'rm -rf "$BUILD"' EXIT
OUTPUT="${1:-$PWD/dist/ALAS.app}"
[[ ! -e "$OUTPUT" ]] || { echo "目标已存在，请使用新输出路径：$OUTPUT"; exit 1; }
xcodebuild -project 'ALAS for macOS.xcodeproj' -scheme 'ALAS for macOS' \
    -destination 'platform=macOS,arch=arm64' -configuration Release \
    -derivedDataPath "$BUILD" CODE_SIGNING_ALLOWED=NO build
APP="$BUILD/Build/Products/Release/ALAS for macOS.app"
[[ ! -e "$APP/Contents/Resources/ALASData" ]]
[[ ! -e "$APP/Contents/Resources/AzurLaneAutoScript" ]]
/usr/bin/codesign --force --sign - "$APP"
/usr/bin/codesign --verify --deep --strict "$APP"
mkdir -p "$(dirname "$OUTPUT")"
/usr/bin/ditto "$APP" "$OUTPUT"
/usr/bin/codesign --verify --deep --strict "$OUTPUT"
echo "完整 App：$OUTPUT"
echo '此包使用 ad-hoc 签名，未进行 Developer ID 签名或公证。'
