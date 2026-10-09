#!/usr/bin/env bash
set -euo pipefail
if [ "${SMALLNEXT_UPLOAD_CRASHLYTICS_SYMBOLS:-NO}" != YES ]; then exit 0; fi

app_id=$(/usr/libexec/PlistBuddy -c 'Print :SmallnextFirebaseAppID' "${TARGET_BUILD_DIR}/${INFOPLIST_PATH}")
if [[ ! "$app_id" =~ ^1:[0-9]+:ios:[0-9a-f]+$ ]]; then
  echo 'error: Crashlytics symbol upload requires a valid Firebase app ID.' >&2
  exit 1
fi
sdk="${BUILD_DIR%/Build/*}/SourcePackages/checkouts/firebase-ios-sdk"
"$sdk/Crashlytics/upload-symbols" -ai "$app_id" -p ios \
  "${DWARF_DSYM_FOLDER_PATH}/${DWARF_DSYM_FILE_NAME}"
