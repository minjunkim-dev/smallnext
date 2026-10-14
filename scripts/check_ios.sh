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
# Boot the selected simulator while Xcode builds without a device destination.
xcrun simctl bootstatus "$simulator" -b &
boot_pid=$!
trap 'kill "$boot_pid" 2>/dev/null || true; wait "$boot_pid" 2>/dev/null || true' EXIT
args=()
if [ -n "${IOS_PACKAGES_DIR:-}" ]; then args+=(-clonedSourcePackagesDirPath "$IOS_PACKAGES_DIR"); fi
if [ -n "${IOS_DERIVED_DATA:-}" ]; then args+=(-derivedDataPath "$IOS_DERIVED_DATA"); fi
build_started=$SECONDS
xcodebuild -project apps/ios/Smallnext.xcodeproj -scheme Smallnext \
  -destination 'generic/platform=iOS Simulator' -arch "$(uname -m)" ${args[@]+"${args[@]}"} \
  -onlyUsePackageVersionsFromResolvedFile -showBuildTimingSummary CODE_SIGNING_ALLOWED=NO build-for-testing
printf 'iOS build-for-testing: %ss\n' "$((SECONDS - build_started))"
wait "$boot_pid"
trap - EXIT
if [ -n "${IOS_RESULTS:-}" ]; then args+=(-resultBundlePath "$IOS_RESULTS"); fi
test_started=$SECONDS
xcodebuild -project apps/ios/Smallnext.xcodeproj -scheme Smallnext \
  -destination "platform=iOS Simulator,id=$simulator" ${args[@]+"${args[@]}"} \
  -onlyUsePackageVersionsFromResolvedFile CODE_SIGNING_ALLOWED=NO test-without-building
printf 'iOS test-without-building: %ss\n' "$((SECONDS - test_started))"
