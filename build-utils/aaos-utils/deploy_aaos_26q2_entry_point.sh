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

# ==============================================================================
# AAOS 26Q2 Master Deployment Entry Point
# 1. Syncs source code via checkout_aaos.sh
# 2. Validates commits and applies patches via patch_applier/patch_aaos.py
# 3. Sources dev_utils.sh for build and CVD management tools
# 4. Builds SDV Media and IVI target images
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_log() {
  echo "[DEPLOY-AAOS] $*"
}

_log "Starting AAOS 26Q2 deployment pipeline..."

# Determine output directory (default: ~/Workspace/aaos-26q2 or from -o/--output-dir flag)
# and check for --skip-repo-sync / --no-checkout
OUTPUT_DIR="${HOME}/Workspace/aaos-26q2"
SKIP_REPO_SYNC=false
CHECKOUT_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-repo-sync | --no-checkout)
      SKIP_REPO_SYNC=true
      shift
      ;;
    -o | --output-dir)
      OUTPUT_DIR="$2"
      CHECKOUT_ARGS+=("$1" "$2")
      shift 2
      ;;
    *)
      CHECKOUT_ARGS+=("$1")
      shift
      ;;
  esac
done

# 1. Execute Checkout & Sync Script
if [[ "${SKIP_REPO_SYNC}" == "true" ]]; then
  _log "Step 1/4: Skipping checkout_aaos.sh (--skip-repo-sync specified)."
  if [[ ! -d "${OUTPUT_DIR}" ]]; then
    _log "ERROR: Output directory '${OUTPUT_DIR}' does not exist; cannot skip repo sync."
    exit 1
  fi
else
  _log "Step 1/4: Running checkout_aaos.sh..."
  "${SCRIPT_DIR}/checkout_aaos.sh" "${CHECKOUT_ARGS[@]}"
fi

# 2. Apply Repository Patches using patch_applier/patch_aaos.py
_log "Step 2/4: Applying repository patches using patch_aaos.py (filter='${DEMO_BUILD_AAOS_PATCHES-base}')..."
"${SCRIPT_DIR}/patch_applier/patch_aaos.py" \
  --aaos-dir "${OUTPUT_DIR}" \
  --patch-tag-filter="${DEMO_BUILD_AAOS_PATCHES-base}"

# 3. Source Development Utility Functions (dev_utils.sh)
_log "Step 3/4: Sourcing dev_utils.sh..."
export ANDROID_BUILD_TOP="${OUTPUT_DIR}"
# shellcheck source=build-utils/aaos-utils/dev_utils.sh
source "${SCRIPT_DIR}/dev_utils.sh"

# 4. Build Target Images
_log "Step 4/4: Building AAOS target images..."
build

_log "AAOS 26Q2 deployment pipeline completed successfully!"
_log "Development utility functions (build, launch_2vm, clear_2vm) are now active in your shell environment."
