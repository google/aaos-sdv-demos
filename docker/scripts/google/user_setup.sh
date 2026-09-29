#!/bin/bash

# Copyright 2025-2026 Google LLC
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

# Adapted from cicf-foundations repo:
# https://github.com/GoogleCloudPlatform/cicd-foundation/blob/main/apps/workstations/common/assets/google/scripts/user_setup.sh

set -euo pipefail

# Source common utilities
# shellcheck source=apps/workstations/common/assets/google/scripts/common.sh
source /google/scripts/common.sh

# Sets up the user-specific runtime directory (XDG_RUNTIME_DIR).
setup_runtime_dir() {
  local xdg_runtime_dir="/run/user/${WORKSTATION_UID}"
  log "Setting up XDG_RUNTIME_DIR at ${xdg_runtime_dir}..."
  mkdir -p "${xdg_runtime_dir}"
  chown "${WORKSTATION_UID}:${WORKSTATION_UID}" "${xdg_runtime_dir}"
  chmod 700 "${xdg_runtime_dir}"
}

# Ensures correct ownership of the user home directory and basic group memberships.
setup_home_dir() {
  log "Fixing ownership for /home/${WORKSTATION_USER}..."

  # Ensure user is in basic functional groups
  usermod -aG audio "${WORKSTATION_USER}" || true

  # Ensure the user can use docker if installed
  if getent group docker >/dev/null; then
    usermod -aG docker "${WORKSTATION_USER}" || true
  fi

  # Use the home directory root as a sentinel for the whole tree.
  #
  # LOCAL DEVIATION from cicd-foundation. Upstream runs an unconditional
  # `chown -R -h` over the whole home directory on every boot. For our
  # precompiled aaos disk snapshots, that takes 6 minutes on each startup.

  local home_dir="/home/${WORKSTATION_USER}"
  local want="${WORKSTATION_UID}:${WORKSTATION_UID}"
  local have
  have="$(stat -c '%u:%g' "${home_dir}" 2>/dev/null || true)"

  if [[ "${have}" == "${want}" ]]; then
    log "${home_dir} already owned by ${want}; skipping ownership sweep."
    return 0
  fi

  log "${home_dir} is owned by '${have:-missing}', expected ${want}; sweeping..."

  # Use -h to avoid dereferencing symlinks. -mindepth 1 excludes the root,
  # which is chowned afterwards as the completion marker described above.
  find "${home_dir}" -mindepth 1 \
    \( ! -uid "${WORKSTATION_UID}" -o ! -gid "${WORKSTATION_UID}" \) \
    -exec chown -h "${WORKSTATION_UID}:${WORKSTATION_UID}" {} +

  chown -h "${WORKSTATION_UID}:${WORKSTATION_UID}" "${home_dir}"
}

# Executes any modular user-level hooks (as root, but can use runuser inside).
run_user_setup_hooks() {
  local hook_dir="/google/scripts/user-setup.d"
  if [[ -d "${hook_dir}" ]]; then
    log "Executing foundational user setup hooks from ${hook_dir}..."
    run_hooks "${hook_dir}"
  fi
}

main() {
  if [[ -f /run/user-setup-done ]]; then
    log "User setup already done, skipping."
    exit 0
  fi

  log_event SERVICE_STARTING "Initializing foundational workstation user" SERVICE=user-setup

  setup_runtime_dir
  setup_home_dir
  run_user_setup_hooks

  log_event SERVICE_READY "Foundational user environment initialized" SERVICE=user-setup
  touch /run/user-setup-done
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
