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

# run_remote_wheel.sh
# Automates SSH port forwarding and remote CARLA execution for local steering wheel control.

# --- Default Configuration ---
MACHINE="tmot-gpu-us.c.googlers.com"
REMOTE_BRIDGE=""
REMOTE_PATH="$HOME/Workspace/sdv-demos"
SYNC_MODE=false
WITH_DISPLAY=false

# --- Argument Parsing ---
while [[ "$#" -gt 0 ]]; do
  case $1 in
    --machine=*)
      MACHINE="${1#*=}"
      ;;
    --machine)
      MACHINE="$2"
      shift
      ;;
    --remote-bridge=*)
      REMOTE_BRIDGE="${1#*=}"
      ;;
    --remote-bridge)
      # shellcheck disable=SC2034
      REMOTE_BRIDGE="$2"
      shift
      ;;
    --remote-path=*)
      REMOTE_PATH="${1#*=}"
      ;;
    --remote-path)
      REMOTE_PATH="$2"
      shift
      ;;
    --sync)
      SYNC_MODE=true
      ;;
    --withDisplay)
      WITH_DISPLAY=true
      ;;
    --help)
      echo "Usage: $0 [--machine=HOST] [--remote-bridge=HOST] [--remote-path=PATH] [--sync] [--withDisplay]"
      echo ""
      echo "Arguments:"
      echo "  --machine=HOST        Remote GPU machine hostname (default: $MACHINE)"
      echo "  --remote-bridge=HOST  Remote manyCPU machine hostname for SOME/IP bridge"
      echo "  --remote-path=PATH    Path to repo on remote machine (default: $REMOTE_PATH)"
      echo "  --sync                Enable synchronous mode (default: false)"
      echo "  --withDisplay         Run full client with camera rendering (default: false)"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      ;;
  esac
  shift
done

# --- Python Runtime & Virtual Environment Check ---
PYTHON_EXEC="python3"
VENV_DIR="./.venv"
if [ -d "$VENV_DIR" ]; then
  # shellcheck source=/dev/null
  source "$VENV_DIR/bin/activate"
elif command -v python3.7 > /dev/null 2>&1; then
  PYTHON_EXEC="$(command -v python3.7)"
elif [ -x "/opt/python3.7/bin/python3.7" ]; then
  PYTHON_EXEC="/opt/python3.7/bin/python3.7"
elif [ -x "/usr/local/bin/python3.7" ]; then
  PYTHON_EXEC="/usr/local/bin/python3.7"
else
  echo "Error: Neither local virtual environment '$VENV_DIR' nor Python 3.7 was found."
  echo "Are you not using containerised demo? Run ./setup_someip_bridge.sh --with-pyenv to provision system."
  exit 1
fi

# --- Cleanup Logic ---
cleanup() {
  # Prevent recursive calls
  trap - SIGINT SIGTERM EXIT

  echo -e "\nShutting down local and remote components..."

  # Kill all background jobs started by this script
  active_jobs=$(jobs -p)
  if [ -n "$active_jobs" ]; then
    # shellcheck disable=SC2086
    kill $active_jobs 2> /dev/null
  fi

  # Specific sweep for local components
  pkill -f "manual_control_steeringwheel.py" 2> /dev/null
  pkill -f "steering_control.py" 2> /dev/null
  pkill -f "ssh -N -L 2000:localhost:2000" 2> /dev/null

  echo "Cleanup complete."
  exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# 1. Establish SSH Tunnel
# 2000: RPC, 2001: Sensor Data, 2002: Metadata
echo "Establishing SSH tunnel to $MACHINE (Forwarding 2000, 2001, 2002)..."
ssh -N -L 2000:localhost:2000 -L 2001:localhost:2001 -L 2002:localhost:2002 "$MACHINE" &
# shellcheck disable=SC2034
TUNNEL_PID=$!

# 2. Local Steering Wheel Client Execution (Background)
# We start this in the background so the remote execution can stay in the foreground for signal propagation.
(
  echo "Waiting for remote CARLA to initialize..."
  sleep 15
  echo "Starting local steering wheel control client..."

  SYNC_FLAG=""
  if [ "$SYNC_MODE" = true ]; then
    SYNC_FLAG="--sync"
  fi

  if [ "$WITH_DISPLAY" = true ]; then
    echo "Mode: Windowed (1920x1080)"
    # Ensure we are in the correct directory for wheel_config.ini
    (cd external_utils && "$PYTHON_EXEC" manual_control_steeringwheel.py --host 127.0.0.1 --res 1920x1080 $SYNC_FLAG)
  else
    echo "Mode: Steering only (No camera rendering)"
    (cd external_utils && "$PYTHON_EXEC" steering_control.py --host 127.0.0.1 $SYNC_FLAG)
  fi
) &
# shellcheck disable=SC2034
CLIENT_PID=$!

#  3. Remote CARLA Execution (Foreground)
# REMOTE_BRIDGE_FLAG=""
# if [ -n "$REMOTE_BRIDGE" ]; then
#     REMOTE_BRIDGE_FLAG="--remote-bridge=$REMOTE_BRIDGE"
# fi
# echo "Starting CARLA on remote machine ($MACHINE) in manual-wheel mode..."
# # Running in foreground so SIGINT is propagated to the remote script
# # Use -tt to force PTY allocation
# ssh -tt "$MACHINE" "cd $REMOTE_PATH/someip-bridge && ./run_carla_and_bridge.sh --mode=manual-wheel $REMOTE_BRIDGE_FLAG"
sleep infinity

# If the SSH command exits, trigger cleanup
cleanup
