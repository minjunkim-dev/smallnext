#!/usr/bin/env bash
set -euo pipefail
if [ -z "${DEVELOPER_DIR:-}" ]; then
  pinned=$(python3 -c 'import json; print(json.load(open(".ci/toolchains.json"))["xcode"])')
  if [ -d "/Applications/Xcode_${pinned}.app/Contents/Developer" ]; then
    export DEVELOPER_DIR="/Applications/Xcode_${pinned}.app/Contents/Developer"
  fi
fi
python3 scripts/environment.py ios
simulator=$(python3 scripts/ios_simulator.py)
xcrun simctl boot "$simulator" 2>/dev/null || xcrun simctl bootstatus "$simulator" -b
xcrun simctl bootstatus "$simulator" -b
args=()
if [ -n "${IOS_PACKAGES_DIR:-}" ]; then args+=(-clonedSourcePackagesDirPath "$IOS_PACKAGES_DIR"); fi
if [ -n "${IOS_DERIVED_DATA:-}" ]; then args+=(-derivedDataPath "$IOS_DERIVED_DATA"); fi
if [ -n "${IOS_RESULTS:-}" ]; then args+=(-resultBundlePath "$IOS_RESULTS"); fi
xcodebuild -project apps/ios/Smallnext.xcodeproj -scheme Smallnext \
  -destination "platform=iOS Simulator,id=$simulator" "${args[@]}" \
  -onlyUsePackageVersionsFromResolvedFile CODE_SIGNING_ALLOWED=NO test
