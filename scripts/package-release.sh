#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
STAGING="$(mktemp -d /private/tmp/alas-package.XXXXXX)"
trap 'rm -rf "$STAGING"' EXIT
./scripts/build-app.sh "$STAGING/ALAS.app"
PLIST="$STAGING/ALAS.app/Contents/Info.plist"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$PLIST")"
BUILD="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$PLIST")"
NAME="ALAS-${VERSION}-build${BUILD}-macOS-arm64.zip"
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
