#!/bin/bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Standalone CLI utility to install/update an APEX package on the running
# IVI VM (127.0.0.1:6521) or Media/Core VM (127.0.0.1:6520) and reboot.

set -eo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"

if [[ -f "${SCRIPT_DIR}/dev_utils.sh" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/dev_utils.sh"
elif [[ -f "/google/aaos-utils/dev_utils.sh" ]]; then
  # shellcheck disable=SC1091
  source "/google/aaos-utils/dev_utils.sh"
else
  export ANDROID_BUILD_TOP="${ANDROID_BUILD_TOP:-${HOME}/Workspace/aaos-26q2}"
  export IVI_OUT_DIR_NAME="${IVI_OUT_DIR_NAME:-out-ivi}"
  export IVI_OUT_DIR="${IVI_OUT_DIR:-${ANDROID_BUILD_TOP}/${IVI_OUT_DIR_NAME}}"
fi

_apex_log() {
  echo "[UPDATE-APEX] $*"
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS] <apex_name_or_path>

Update an APEX module on the target Cuttlefish VM and reboot to activate it.

Options:
  --vm <ivi|media>       Select target VM (default: ivi)
                           - ivi:   serial 127.0.0.1:6521, searches ${IVI_OUT_DIR}
                           - media: serial 127.0.0.1:6520, searches ${ANDROID_BUILD_TOP}/out
  -s, --serial <serial>  Override target ADB device serial
  -b, --build            Build the APEX target via build_soong_target before updating
  --no-reboot            Stage the APEX update without rebooting the device
  -h, --help             Show this help message and exit

Examples:
  $(basename "$0") com.android.sdv.sample.vhal_proxy
  $(basename "$0") --vm ivi --build com.android.sdv.sample.vhal_proxy
  $(basename "$0") --vm media com.android.sdv.sample.gapb
EOF
}

VM_TYPE="ivi"
ADB_SERIAL=""
DO_BUILD=false
DO_REBOOT=true
APEX_INPUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --vm)
      if [[ $# -lt 2 ]]; then
        _apex_log "Error: --vm requires an argument (ivi or media)." >&2
        exit 1
      fi
      VM_TYPE="$2"
      shift 2
      ;;
    --vm=*)
      VM_TYPE="${1#*=}"
      shift
      ;;
    -s | --serial)
      if [[ $# -lt 2 ]]; then
        _apex_log "Error: $1 requires a device serial argument." >&2
        exit 1
      fi
      ADB_SERIAL="$2"
      shift 2
      ;;
    --serial=*)
      ADB_SERIAL="${1#*=}"
      shift
      ;;
    -b | --build)
      DO_BUILD=true
      shift
      ;;
    --no-reboot)
      DO_REBOOT=false
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    -*)
      _apex_log "Error: Unknown option '$1'." >&2
      usage >&2
      exit 1
      ;;
    *)
      if [[ -n "${APEX_INPUT}" ]]; then
        _apex_log "Error: Only one APEX name or path may be specified (got '${APEX_INPUT}' and '$1')." >&2
        usage >&2
        exit 1
      fi
      APEX_INPUT="$1"
      shift
      ;;
  esac
done

if [[ -z "${APEX_INPUT}" ]]; then
  _apex_log "Error: An APEX module name or .apex file path is required." >&2
  usage >&2
  exit 1
fi

case "${VM_TYPE,,}" in
  ivi)
    DEFAULT_SERIAL="127.0.0.1:6521"
    PRODUCT_DIRS=(
      "${IVI_OUT_DIR}/target/product/sdv_ivi_cf"
      "${IVI_OUT_DIR}/target/product/sdv_ivi_cf_ds"
      "${ANDROID_BUILD_TOP}/out/target/product/sdv_ivi_cf"
      "${ANDROID_BUILD_TOP}/out/target/product/sdv_ivi_cf_ds"
    )
    ;;
  media | core)
    DEFAULT_SERIAL="127.0.0.1:6520"
    PRODUCT_DIRS=(
      "${ANDROID_BUILD_TOP}/out/target/product/sdv_har_cf"
      "${ANDROID_BUILD_TOP}/out/target/product/sdv_media_har_cf"
    )
    ;;
  *)
    _apex_log "Error: Invalid --vm value '${VM_TYPE}'. Expected 'ivi' or 'media'." >&2
    exit 1
    ;;
esac

ADB_SERIAL="${ADB_SERIAL:-${DEFAULT_SERIAL}}"

# Derive module name if not passing an explicit file path
APEX_MODULE_NAME="$(basename "${APEX_INPUT}")"
APEX_MODULE_NAME="${APEX_MODULE_NAME%.apex}"

if [[ "${DO_BUILD}" == "true" ]]; then
  _apex_log "Building APEX module '${APEX_MODULE_NAME}' for VM '${VM_TYPE}'..."
  "${SCRIPT_DIR}/build_soong_target.sh" --vm "${VM_TYPE}" "${APEX_MODULE_NAME}"
fi

# Resolve the .apex file path
APEX_FILE=""
if [[ -f "${APEX_INPUT}" ]]; then
  APEX_FILE="$(readlink -f "${APEX_INPUT}")"
else
  for prod_dir in "${PRODUCT_DIRS[@]}"; do
    for part in vendor product system system_ext; do
      candidate="${prod_dir}/${part}/apex/${APEX_MODULE_NAME}.apex"
      if [[ -f "${candidate}" ]]; then
        APEX_FILE="${candidate}"
        break 2
      fi
    done
  done
fi

if [[ -z "${APEX_FILE}" || ! -f "${APEX_FILE}" ]]; then
  _apex_log "Error: Could not find built APEX file for '${APEX_INPUT}'." >&2
  _apex_log "Checked product directories: ${PRODUCT_DIRS[*]}" >&2
  _apex_log "Run 'build_soong_target --vm ${VM_TYPE} ${APEX_MODULE_NAME}' or pass --build." >&2
  exit 1
fi

# Locate adb binary
ADB_BIN=""
if command -v adb >/dev/null 2>&1; then
  ADB_BIN="$(command -v adb)"
elif [[ -x "${ANDROID_BUILD_TOP}/out/host/linux-x86/bin/adb" ]]; then
  ADB_BIN="${ANDROID_BUILD_TOP}/out/host/linux-x86/bin/adb"
elif [[ -x "${IVI_OUT_DIR}/host/linux-x86/bin/adb" ]]; then
  ADB_BIN="${IVI_OUT_DIR}/host/linux-x86/bin/adb"
else
  _apex_log "Error: Could not locate 'adb' binary in PATH or ${ANDROID_BUILD_TOP}/out/host/linux-x86/bin/adb." >&2
  exit 1
fi

_apex_log "Target VM: ${VM_TYPE} (${ADB_SERIAL})"
_apex_log "APEX file: ${APEX_FILE}"

# Ensure ADB connection
if [[ "${ADB_SERIAL}" == *:* ]]; then
  "${ADB_BIN}" connect "${ADB_SERIAL}" >/dev/null 2>&1 || true
fi
"${ADB_BIN}" -s "${ADB_SERIAL}" wait-for-device

_apex_log "Staging APEX update on ${ADB_SERIAL}..."
if "${ADB_BIN}" -s "${ADB_SERIAL}" install --staged -d "${APEX_FILE}"; then
  _apex_log "Staged APEX via 'adb install --staged -d'."
else
  _apex_log "'adb install --staged -d' failed; falling back to pushing directly to /data/apex/active/${APEX_MODULE_NAME}@1.apex..."
  "${ADB_BIN}" -s "${ADB_SERIAL}" root >/dev/null
  if [[ "${ADB_SERIAL}" == *:* ]]; then
    "${ADB_BIN}" connect "${ADB_SERIAL}" >/dev/null 2>&1 || true
  fi
  "${ADB_BIN}" -s "${ADB_SERIAL}" wait-for-device
  "${ADB_BIN}" -s "${ADB_SERIAL}" push "${APEX_FILE}" "/data/apex/active/${APEX_MODULE_NAME}@1.apex"
  "${ADB_BIN}" -s "${ADB_SERIAL}" shell "chmod 644 /data/apex/active/${APEX_MODULE_NAME}@1.apex && sync"
  _apex_log "Installed APEX to /data/apex/active/${APEX_MODULE_NAME}@1.apex."
fi

if [[ "${DO_REBOOT}" == "true" ]]; then
  _apex_log "Rebooting ${ADB_SERIAL} to activate updated APEX..."
  "${ADB_BIN}" -s "${ADB_SERIAL}" reboot
  sleep 3
  if [[ "${ADB_SERIAL}" == *:* ]]; then
    for _ in {1..30}; do
      if "${ADB_BIN}" connect "${ADB_SERIAL}" 2>/dev/null | grep -qE "connected to|already connected"; then
        break
      fi
      sleep 2
    done
  fi
  "${ADB_BIN}" -s "${ADB_SERIAL}" wait-for-device
  _apex_log "Waiting for boot_completed on ${ADB_SERIAL}..."
  # shellcheck disable=SC2016
  "${ADB_BIN}" -s "${ADB_SERIAL}" shell 'while [[ "$(getprop sys.boot_completed)" != "1" ]]; do sleep 1; done'
  _apex_log "Device ${ADB_SERIAL} rebooted and ready. Active mount:"
  "${ADB_BIN}" -s "${ADB_SERIAL}" shell "ls -la /apex/${APEX_MODULE_NAME}/" || true
else
  _apex_log "Skipping reboot (--no-reboot specified). Reboot ${ADB_SERIAL} to activate the APEX."
fi
