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

# Configure a 64 GiB swapfile on the persistent /home volume for user workstations
# (< 200 GiB physical RAM, e.g. n1-standard-32 with 120 GB RAM) so that AOSP
# soong_build Blueprint analysis (~110 GiB peak) does not get OOM-killed (exit=137)
# when Cuttlefish VMs and IDEs are running concurrently.

SWAPFILE="${WORKSTATION_SWAPFILE:-/home/.workstation/swapfile}"
SWAP_SIZE_GB="${WORKSTATION_SWAP_SIZE_GB:-64}"
MAX_RAM_KB_FOR_SWAP=$((200 * 1024 * 1024)) # 200 GiB in KiB
MIN_AVAIL_KB=$(( (SWAP_SIZE_GB + 64) * 1024 * 1024 )) # Require at least swap size + 64 GiB free

setup_swap() {
  # 1. Skip if swap is already active
  if awk 'NR > 1 { exit 0 } END { exit 1 }' /proc/swaps 2>/dev/null; then
    return 0
  fi

  # 2. Skip on high-RAM machines
  local mem_total_kb
  mem_total_kb="$(awk '/^MemTotal:/ { print $2 }' /proc/meminfo 2>/dev/null || echo 0)"
  if (( mem_total_kb == 0 || mem_total_kb >= MAX_RAM_KB_FOR_SWAP )); then
    return 0
  fi

  # 3. Ensure /home is backed by a real disk filesystem (swapon fails on overlayfs/tmpfs)
  local fs_type
  fs_type="$(stat -f -c '%T' /home 2>/dev/null || true)"
  case "${fs_type}" in
    "" | overlay* | tmpfs)
      return 0
      ;;
  esac

  mkdir -p "$(dirname "${SWAPFILE}")"

  # 4. Allocate swapfile if not already present at the expected size
  local target_bytes=$((SWAP_SIZE_GB * 1024 * 1024 * 1024))
  local current_bytes=0
  if [[ -f "${SWAPFILE}" ]]; then
    current_bytes="$(stat -c '%s' "${SWAPFILE}" 2>/dev/null || echo 0)"
  fi

  if (( current_bytes != target_bytes )); then
    local avail_kb
    avail_kb="$(df -Pk /home 2>/dev/null | awk 'NR == 2 { print $4 }' || echo 0)"
    if (( avail_kb < MIN_AVAIL_KB )); then
      echo "[swap-setup] Skipping swapfile creation: insufficient free space on /home (${avail_kb} KiB available)." >&2
      return 0
    fi
    rm -f "${SWAPFILE}"
    fallocate -l "${SWAP_SIZE_GB}G" "${SWAPFILE}" || return 0
  fi

  chmod 600 "${SWAPFILE}" || return 0
  mkswap "${SWAPFILE}" >/dev/null 2>&1 || return 0
  swapon "${SWAPFILE}" 2>/dev/null || true
}

setup_swap || true
