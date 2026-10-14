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
# Standalone CLI utility to build one or more Soong modules for either the
# IVI VM (OUT_DIR=out-ivi) or the Media/Core VM (OUT_DIR=out).

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
  echo "[AAOS-BUILD] Error: Could not locate dev_utils.sh." >&2
  exit 1
fi

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS] <soong_target> [<soong_target2> ...]

Build one or more Soong modules for the specified AAOS VM target.

Options:
  --vm <ivi|media>            Select target VM (default: ivi)
                                - ivi:   ${IVI_LUNCH_TARGET} (OUT_DIR=${IVI_OUT_DIR_NAME})
                                - media: ${SDV_MEDIA_LUNCH_TARGET} (OUT_DIR=out)
  -t, --lunch-target <target> Explicitly specify lunch target
  -h, --help                  Show this help message and exit

Examples:
  $(basename "$0") com.android.sdv.sample.vhal_proxy
  $(basename "$0") --vm ivi android.hardware.automotive.vehicle@V1-sdv-emulator-service com.android.sdv.sample.vhal_proxy
  $(basename "$0") --vm media com.android.sdv.sample.gapb
EOF
}

VM_TYPE="ivi"
LUNCH_TARGET_OVERRIDE=""
TARGETS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --vm)
      if [[ $# -lt 2 ]]; then
        _log "Error: --vm requires an argument (ivi or media)." >&2
        exit 1
      fi
      VM_TYPE="$2"
      shift 2
      ;;
    --vm=*)
      VM_TYPE="${1#*=}"
      shift
      ;;
    -t | --lunch-target)
      if [[ $# -lt 2 ]]; then
        _log "Error: $1 requires a lunch target argument." >&2
        exit 1
      fi
      LUNCH_TARGET_OVERRIDE="$2"
      shift 2
      ;;
    --lunch-target=*)
      LUNCH_TARGET_OVERRIDE="${1#*=}"
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    -*)
      _log "Error: Unknown option '$1'." >&2
      usage >&2
      exit 1
      ;;
    *)
      TARGETS+=("$1")
      shift
      ;;
  esac
done

if [[ ${#TARGETS[@]} -eq 0 ]]; then
  _log "Error: At least one Soong target must be specified." >&2
  usage >&2
  exit 1
fi

if [[ -n "${LUNCH_TARGET_OVERRIDE}" ]]; then
  SELECTED_LUNCH_TARGET="${LUNCH_TARGET_OVERRIDE}"
else
  case "${VM_TYPE,,}" in
    ivi)
      SELECTED_LUNCH_TARGET="${IVI_LUNCH_TARGET}"
      ;;
    media | core)
      SELECTED_LUNCH_TARGET="${SDV_MEDIA_LUNCH_TARGET}"
      ;;
    *)
      _log "Error: Invalid --vm value '${VM_TYPE}'. Expected 'ivi' or 'media'." >&2
      exit 1
      ;;
  esac
fi

if [[ ! -d "${ANDROID_BUILD_TOP}" ]]; then
  _log "Error: ANDROID_BUILD_TOP directory '${ANDROID_BUILD_TOP}' does not exist." >&2
  exit 1
fi

cd "${ANDROID_BUILD_TOP}"

_ensure_envsetup

if _is_ivi_target "${SELECTED_LUNCH_TARGET}"; then
  export OUT_DIR="${IVI_OUT_DIR_NAME}"
  _log "Using IVI output directory: OUT_DIR=${OUT_DIR} (${IVI_OUT_DIR})"
else
  unset OUT_DIR
  _log "Using default output directory: ${ANDROID_BUILD_TOP}/out"
fi

_log "Executing lunch for target: ${SELECTED_LUNCH_TARGET}..."
lunch "${SELECTED_LUNCH_TARGET}"

_log "Building Soong target(s): ${TARGETS[*]} (lunch: ${SELECTED_LUNCH_TARGET}, OUT_DIR: ${OUT_DIR:-${ANDROID_BUILD_TOP}/out})..."

MAX_RETRIES="${BUILD_MAX_RETRIES:-2}"
ATTEMPT=1
BUILD_OK=0

while [[ "${ATTEMPT}" -le "${MAX_RETRIES}" ]]; do
  _log "Compilation attempt ${ATTEMPT}/${MAX_RETRIES}..."
  if m "${TARGETS[@]}"; then
    BUILD_OK=1
    break
  else
    _log "Build compilation failed on attempt ${ATTEMPT}."
    ATTEMPT=$((ATTEMPT + 1))
    sleep 2
  fi
done

if [[ "${BUILD_OK}" -ne 1 ]]; then
  _log "Error: Build failed after ${MAX_RETRIES} attempts for target(s): ${TARGETS[*]}." >&2
  exit 1
fi

_log "Flushing filesystem buffers to persistent disk (sync)..."
sync

_log "Successfully built target(s): ${TARGETS[*]}"
