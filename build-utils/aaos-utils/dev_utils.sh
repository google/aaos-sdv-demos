# shellcheck shell=bash
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
# Helper tools for building AAOS targets and launching CVD instances.
# Intended to be sourced from interactive bash shells or ~/.bashrc.

export ANDROID_BUILD_TOP="${ANDROID_BUILD_TOP:-${HOME}/Workspace/aaos-26q2}"
export SDV_MEDIA_LUNCH_TARGET="${SDV_MEDIA_LUNCH_TARGET:-sdv_media_har_cf-trunk_staging-userdebug}"
export IVI_LUNCH_TARGET="${IVI_LUNCH_TARGET:-sdv_ivi_cf_ds-trunk_staging-userdebug}"
export IVI_OUT_DIR_NAME="${IVI_OUT_DIR_NAME:-out-ivi}"
export IVI_OUT_DIR="${IVI_OUT_DIR:-${ANDROID_BUILD_TOP}/${IVI_OUT_DIR_NAME}}"

# Generate out/soong/rust-project.json during initial builds and keep Soong's
# tracked environment aligned with ASfP (which sets SOONG_GEN_RUST_PROJECT=1
# whenever "rust" is in .asfp-project other_languages).
export SOONG_GEN_RUST_PROJECT="${SOONG_GEN_RUST_PROJECT:-1}"

if ! declare -f _log > /dev/null 2>&1; then
  _log() {
    echo "[AAOS-BUILD] $*"
  }
fi

_ensure_envsetup() {
  if ! declare -f lunch > /dev/null 2>&1; then
    _log "Setting up build environment..."
    local orig_dir
    orig_dir="$(pwd)"
    cd "$ANDROID_BUILD_TOP" || return 1
    # shellcheck disable=SC1091 # build/envsetup.sh is located in external $ANDROID_BUILD_TOP checkout
    source build/envsetup.sh
    cd "$orig_dir" || return 1
  fi
}

_is_ivi_target() {
  local target="$1"
  [[ "$target" == "$IVI_LUNCH_TARGET" || "$target" == sdv_ivi* ]]
}

lunch_media() {
  local orig_dir
  orig_dir="$(pwd)"
  cd "$ANDROID_BUILD_TOP" || return 1
  _ensure_envsetup || return 1
  unset OUT_DIR
  lunch "$SDV_MEDIA_LUNCH_TARGET"
  cd "$orig_dir" || return 1
}

lunch_ivi() {
  local orig_dir
  orig_dir="$(pwd)"
  cd "$ANDROID_BUILD_TOP" || return 1
  _ensure_envsetup || return 1
  export OUT_DIR="$IVI_OUT_DIR_NAME"
  lunch "$IVI_LUNCH_TARGET"
  cd "$orig_dir" || return 1
}

build_target() {
  local build_target="$1"
  local artifact="${2:-}"
  local orig_dir
  orig_dir="$(pwd)"
  cd "$ANDROID_BUILD_TOP" || return 1

  _ensure_envsetup

  if _is_ivi_target "$build_target"; then
    export OUT_DIR="$IVI_OUT_DIR_NAME"
    _log "Using separate IVI output directory: OUT_DIR=${OUT_DIR} (${IVI_OUT_DIR})"
  else
    unset OUT_DIR
    _log "Using default output directory: ${ANDROID_BUILD_TOP}/out"
  fi

  _log "Executing lunch for target: ${build_target}..."
  lunch "${build_target}"

  local build_cmd=("m")
  if [[ -n "$artifact" ]]; then
    build_cmd+=("$artifact")
  fi
  _log "Starting build compilation for artifact: ${artifact:-<default>} (lunch: ${build_target}, OUT_DIR: ${OUT_DIR:-${ANDROID_BUILD_TOP}/out})."

  # Retry loop for compilation failures
  local max_retries="${BUILD_MAX_RETRIES:-2}"
  local attempt=1
  local build_ok=0

  while [ "$attempt" -le "$max_retries" ]; do
    _log "Compilation attempt ${attempt}/${max_retries}..."
    if "${build_cmd[@]}"; then
      build_ok=1
      break
    else
      _log "Build compilation failed on attempt ${attempt}."
      attempt=$((attempt + 1))
      sleep 2
    fi
  done

  if [ "$build_ok" -ne 1 ]; then
    _log "Error: Build failed after ${max_retries} attempts for target ${build_target}${artifact:+ ($artifact)}."
    cd "$orig_dir" || return 1
    return 1
  fi

  _log "Flushing filesystem buffers to persistent disk (sync)..."
  sync

  _log "Build completed successfully for ${build_target}${artifact:+ ($artifact)}!"
  cd "$orig_dir" || return 1
}

build_media() {
  build_target "$SDV_MEDIA_LUNCH_TARGET" "${1:-}"
}

build_ivi() {
  build_target "$IVI_LUNCH_TARGET" "${1:-}"
}

AAOS_UTILS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CVD_MULTI_CONFIG="${CVD_MULTI_CONFIG:-${AAOS_UTILS_DIR}/ds-multi-cvd-config.json}"

build() {
  build_target "$SDV_MEDIA_LUNCH_TARGET" "" || return 1
  build_target "$IVI_LUNCH_TARGET" "" || return 1
  _log "All build targets completed successfully."
  sync
}

launch_2vm() {
  local orig_dir
  orig_dir="$(pwd)"
  cd "$ANDROID_BUILD_TOP" || return 1

  local media_dir="${ANDROID_BUILD_TOP}/out/target/product/sdv_har_cf"
  [ ! -d "$media_dir" ] && media_dir="${ANDROID_BUILD_TOP}/out/target/product/sdv_media_har_cf"
  local ivi_dir="${IVI_OUT_DIR}/target/product/sdv_ivi_cf_ds"
  [ ! -d "$ivi_dir" ] && ivi_dir="${IVI_OUT_DIR}/target/product/sdv_ivi_cf"
  [ ! -d "$ivi_dir" ] && ivi_dir="${ANDROID_BUILD_TOP}/out/target/product/sdv_ivi_cf_ds"
  [ ! -d "$ivi_dir" ] && ivi_dir="${ANDROID_BUILD_TOP}/out/target/product/sdv_ivi_cf"

  if [ ! -d "$media_dir" ] || [ ! -d "$ivi_dir" ]; then
    _log "Error: Missing required build outputs for dual-CVD launch:"
    [ ! -d "$media_dir" ] && _log "  - Media/Cluster build not found (checked ${ANDROID_BUILD_TOP}/out/target/product/sdv_har_cf and sdv_media_har_cf)"
    [ ! -d "$ivi_dir" ] && _log "  - IVI build not found (checked ${IVI_OUT_DIR}/target/product/sdv_ivi_cf and sdv_ivi_cf_ds)"
    _log "Please run 'build' first (or 'build_media' / 'build_ivi') before launching CVDs."
    cd "$orig_dir" || return 1
    return 1
  fi

  if [ -f "${media_dir}/android-info.txt" ] && ! grep -q '^gfxstream=supported' "${media_dir}/android-info.txt"; then
    printf 'gfxstream=supported\ngfxstream_gl_program_binary_link_status=supported\n' >> "${media_dir}/android-info.txt"
  fi

  _ensure_envsetup || return 1
  unset OUT_DIR
  lunch "$SDV_MEDIA_LUNCH_TARGET" # any of the 2 targets would work
  cvd load "$CVD_MULTI_CONFIG"
  local launch_status=$?
  cd "$orig_dir" || return 1
  return $launch_status
}

clear_2vm() {
  local orig_dir
  orig_dir="$(pwd)"
  cd "$ANDROID_BUILD_TOP" || return 1
  _ensure_envsetup || return 1
  unset OUT_DIR
  lunch "$SDV_MEDIA_LUNCH_TARGET" # any of the 2 targets would work
  cvd clear
  local clear_status=$?
  cvd reset -y >/dev/null 2>&1 || true
  cd "$orig_dir" || return 1
  return $clear_status
}

