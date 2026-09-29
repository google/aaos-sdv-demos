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

# Interactive shell utilities and welcome message
if [[ $- != *i* ]]; then
  # shellcheck disable=SC2317
  return 0 2> /dev/null || true
fi

cat /google/sdv-bashrc-hook/ascii_art
echo "Welcome to the aaos-sdv dev env!"
echo '"cat /google/sdv-bashrc-hook/README" to get started'

# Function for launching carla in a standalone terminal
launch_carla() {
  gnome-terminal -- bash -ic 'trap exit SIGINT; /google/someip-bridge/run_carla_and_bridge.sh --mode=manual-wasd; exec bash'
}

# Source cvd-wrapping utils
if [ -f /google/aaos-utils/dev_utils.sh ]; then
  # shellcheck disable=SC1091
  source /google/aaos-utils/dev_utils.sh
fi
