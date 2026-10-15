#!/usr/bin/env bash
set -euo pipefail
if [ -z "${DEVELOPER_DIR:-}" ]; then
  pinned=$(python3 -c 'import json; print(json.load(open(".ci/toolchains.json"))["xcode"])')
  if [ -d "/Applications/Xcode_${pinned}.app/Contents/Developer" ]; then
    export DEVELOPER_DIR="/Applications/Xcode_${pinned}.app/Contents/Developer"
  fi
fi
python3 scripts/environment.py ios
# PR CI sets IOS_SIMULATOR_TESTS=0: the first simulator boot holds the runner CPU for minutes.
simulator_tests=${IOS_SIMULATOR_TESTS:-1}
case "$simulator_tests" in
  0|1) ;;
  *) echo "IOS_SIMULATOR_TESTS must be 0 or 1, got '$simulator_tests'." >&2; exit 2 ;;
esac
package_args=()
if [ -n "${IOS_PACKAGE_BUILD:-}" ]; then package_args+=(--scratch-path "$IOS_PACKAGE_BUILD"); fi
package_started=$SECONDS
swift test --package-path apps/ios/Packages/SmallnextCore --force-resolved-versions ${package_args[@]+"${package_args[@]}"}
printf 'iOS package swift test: %ss\n' "$((SECONDS - package_started))"
if [ "$simulator_tests" = 1 ]; then
  simulator=$(python3 scripts/ios_simulator.py)
  # Boot the selected simulator while Xcode builds without a device destination.
  xcrun simctl bootstatus "$simulator" -b &
  boot_pid=$!
  trap 'kill "$boot_pid" 2>/dev/null || true; wait "$boot_pid" 2>/dev/null || true' EXIT
fi
args=()
if [ -n "${IOS_PACKAGES_DIR:-}" ]; then args+=(-clonedSourcePackagesDirPath "$IOS_PACKAGES_DIR"); fi
if [ -n "${IOS_DERIVED_DATA:-}" ]; then args+=(-derivedDataPath "$IOS_DERIVED_DATA"); fi
build_started=$SECONDS
xcodebuild -project apps/ios/Smallnext.xcodeproj -scheme Smallnext \
  -destination 'generic/platform=iOS Simulator' ${args[@]+"${args[@]}"} \
  -onlyUsePackageVersionsFromResolvedFile -skipPackageUpdates -showBuildTimingSummary \
  ARCHS="$(uname -m)" ONLY_ACTIVE_ARCH=YES CODE_SIGNING_ALLOWED=NO build-for-testing
printf 'iOS build-for-testing: %ss\n' "$((SECONDS - build_started))"
if [ "$simulator_tests" = 0 ]; then
  echo 'iOS simulator tests: skipped (IOS_SIMULATOR_TESTS=0)'
  exit 0
fi
wait "$boot_pid"
trap - EXIT
if [ -n "${IOS_RESULTS:-}" ]; then args+=(-resultBundlePath "$IOS_RESULTS"); fi
test_started=$SECONDS
xcodebuild -project apps/ios/Smallnext.xcodeproj -scheme Smallnext \
  -destination "platform=iOS Simulator,id=$simulator" ${args[@]+"${args[@]}"} \
  -onlyUsePackageVersionsFromResolvedFile -skipPackageUpdates CODE_SIGNING_ALLOWED=NO test-without-building
printf 'iOS test-without-building: %ss\n' "$((SECONDS - test_started))"
