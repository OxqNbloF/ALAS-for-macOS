#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f 'ALAS for macOS/Runtime/bundled/core.bundle' ]]; then
    echo '提示：未找到内置运行时种子，本次发布包首次启动需要联网。'
    echo '      可用 ./scripts/bundle-runtime.sh 生成后再打包。'
fi
STAGING="$(mktemp -d /private/tmp/alas-package.XXXXXX)"
trap 'rm -rf "$STAGING"' EXIT
./scripts/build-app.sh "$STAGING/ALAS.app"
PLIST="$STAGING/ALAS.app/Contents/Info.plist"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$PLIST")"
NAME="ALAS-${VERSION}-macOS-arm64.zip"
mkdir -p dist
[[ ! -e "dist/$NAME" && ! -e "dist/$NAME.sha256" ]] || { echo "发布附件已存在：$NAME" >&2; exit 1; }
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$STAGING/ALAS.app" "$STAGING/$NAME"
mkdir "$STAGING/verify"
/usr/bin/ditto -x -k "$STAGING/$NAME" "$STAGING/verify"
/usr/bin/codesign --verify --deep --strict "$STAGING/verify/ALAS.app"
mv "$STAGING/$NAME" "dist/$NAME"
cd dist
/usr/bin/shasum -a 256 "$NAME" > "$NAME.sha256"
echo "发布附件：$PWD/$NAME"
echo "校验文件：$PWD/$NAME.sha256"
