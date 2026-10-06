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

# Source recipe environment variables
# shellcheck disable=SC1091
source /google/recipe/base.sh

# Enable Application Default Credentials (ADC) auth for Antigravity CLI (agy)
export AGY_ADC_AUTH="${AGY_ADC_AUTH:-true}"

# CARLA Environment
if [ -z "${CARLA_DIR:-}" ]; then
  if [ -n "${HOME:-}" ] && [ -d "${HOME}/Workspace/carla-installation" ]; then
    export CARLA_DIR="${HOME}/Workspace/carla-installation"
  elif [ -d "/home/user/Workspace/carla-installation" ]; then
    export CARLA_DIR="/home/user/Workspace/carla-installation"
  else
    export CARLA_DIR="${HOME:-}/Workspace/carla-installation"
  fi
fi

if [ -n "${CARLA_DIR:-}" ] && [ -d "${CARLA_DIR}" ]; then
  case ":${PATH:-}:" in
    *":${CARLA_DIR}:"*) ;;
    *) export PATH="${CARLA_DIR}:${PATH:-}" ;;
  esac
fi

cat /google/sdv-bashrc-hook/ascii_art
printf '\033[1;38;5;25mWelcome to the aaos-sdv dev env!\033[0m\n'
printf 'Run \033[1;38;5;23;48;5;254m cat /google/sdv-bashrc-hook/README \033[0m to get started\n'

# Function for installing CARLA interactively when not pre-baked
install_carla() {
  if [ -d "${CARLA_DIR}" ] && [ -f "${CARLA_DIR}/CarlaUE4.sh" ]; then
    echo "[CARLA] CARLA is already installed at ${CARLA_DIR}. Skipping installation."
    return 0
  fi
  DEMO_BUILD_PREINSTALL_CARLA="true" /google/carla915-utils/setup_carla.sh --install-dir="${CARLA_DIR}" "$@" || return $?
  if [ -d "${CARLA_DIR}" ]; then
    case ":${PATH:-}:" in
      *":${CARLA_DIR}:"*) ;;
      *) export PATH="${CARLA_DIR}:${PATH:-}" ;;
    esac
  fi
}

# Function for launching carla in a standalone terminal
launch_carla() {
  if [ ! -f "${CARLA_DIR}/CarlaUE4.sh" ]; then
    echo "[CARLA] Error: CARLA is not installed at ${CARLA_DIR}."
    echo "[CARLA] Please run 'install_carla' first to accept the Unreal Engine EULA and install CARLA."
    return 1
  fi
  gnome-terminal -- bash -ic 'trap exit SIGINT; /google/someip-bridge/run_carla_and_bridge.sh --mode=manual-wasd; exec bash'
}

# Function for launching Android Studio for Platform (ASfP)
asfp() {
  if [[ $# -eq 0 ]]; then
    set -- "${HOME}/Workspace/asfp-project"
  fi
  XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}" \
  DISPLAY="${DISPLAY:-:0}" \
    /opt/android-studio-for-platform-canary/bin/studio "$@" > /dev/null 2>&1 < /dev/null & disown
}

# Alias for launching Antigravity IDE
alias antigravity_ide='/opt/Antigravity-x64/antigravity --no-sandbox'

# Alias for visualizing Cuttlefish instances in Chrome
alias visualize_cvd='google-chrome --allow-insecure-localhost --user-data-dir=/tmp/dev-chrome-profile https://localhost:8444 > /dev/null 2>&1 < /dev/null & disown'

# Source cvd-wrapping utils
if [ -f /google/aaos-utils/dev_utils.sh ]; then
  # shellcheck disable=SC1091
  source /google/aaos-utils/dev_utils.sh
fi
