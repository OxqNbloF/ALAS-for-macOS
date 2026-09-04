#!/bin/bash
set -euo pipefail
# 构建 Release App，签名并校验后复制到新路径。
cd "$(dirname "$0")/.."
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode-beta.app/Contents/Developer}"
IDENTITY="${ALAS_SIGN_IDENTITY:--}"
BUILD="$(mktemp -d /private/tmp/alas-release.XXXXXX)"
OUTPUT="${1:-$PWD/dist/ALAS.app}"
[[ ! -e "$OUTPUT" ]] || { echo "目标已存在，请使用新输出路径：$OUTPUT"; exit 1; }
xcodebuild -project 'ALAS for macOS.xcodeproj' -scheme 'ALAS for macOS' \
    -destination 'platform=macOS,arch=arm64' -configuration Release \
    -derivedDataPath "$BUILD" CODE_SIGNING_ALLOWED=NO build
APP="$BUILD/Build/Products/Release/ALAS for macOS.app"
[[ ! -e "$APP/Contents/Resources/ALASData" ]]
[[ ! -e "$APP/Contents/Resources/AzurLaneAutoScript" ]]
/usr/bin/codesign --force --sign "$IDENTITY" --options runtime "$APP"
/usr/bin/codesign --verify --deep --strict "$APP"
/usr/bin/codesign -d --entitlements :- "$APP" > "$BUILD/entitlements.plist"
if [[ -s "$BUILD/entitlements.plist" ]] &&
    /usr/libexec/PlistBuddy -c 'Print :com.apple.security.app-sandbox' "$BUILD/entitlements.plist" 2>/dev/null | /usr/bin/grep -qx true; then
    echo '错误：产物仍启用了 App Sandbox。'; exit 1
fi
mkdir -p "$(dirname "$OUTPUT")"
/usr/bin/ditto "$APP" "$OUTPUT"
/usr/bin/codesign --verify --deep --strict "$OUTPUT"
echo "完整 App：$OUTPUT"
if [[ "$IDENTITY" = - ]]; then
    echo '此包为本机 ad-hoc 签名测试包，未进行 Developer ID 签名或公证。'
fi
