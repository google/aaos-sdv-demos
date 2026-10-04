#!/usr/bin/env bash
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

set -eo pipefail

# Configuration
CARLA_VERSION="${DEMO_BUILD_CARLA_VERSION:-0.9.15}"
CARLA_MAP="${DEMO_BUILD_CARLA_MAP:-Town15}"
CARLA_URL="${CARLA_URL:-https://downloads.carlasim.com/Linux/CARLA_${CARLA_VERSION}.tar.gz}"
MAPS_URL="${MAPS_URL:-https://downloads.carlasim.com/Linux/AdditionalMaps_${CARLA_VERSION}.tar.gz}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/Workspace/carla-installation}"
ARCHIVE_NAME="CARLA_${CARLA_VERSION}.tar.gz"
MAPS_FILENAME="AdditionalMaps_${CARLA_VERSION}.tar.gz"
SKIP_LICENSE_AGREEMENT=false

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-license-agreement | -y | --yes)
      SKIP_LICENSE_AGREEMENT=true
      shift
      ;;
    --install-dir=*)
      INSTALL_DIR="${1#*=}"
      shift
      ;;
    -h | --help)
      echo "Usage: $(basename "$0") [--skip-license-agreement|-y|--yes] [--install-dir=<path>]"
      echo "  --install-dir=<path>       Target directory for CARLA binaries (default: ~/Workspace/carla-installation)"
      echo "  --skip-license-agreement   Skip interactive Unreal Engine EULA prompt (-y, --yes alias)"
      exit 0
      ;;
    *)
      shift
      ;;
  esac
done

if [[ "${DEMO_BUILD_PREINSTALL_CARLA:-}" == "false" ]]; then
  log "DEMO_BUILD_PREINSTALL_CARLA is 'false'. Skipping CARLA installation."
  exit 0
elif [[ "${DEMO_BUILD_PREINSTALL_CARLA:-}" != "true" ]]; then
  warn "DEMO_BUILD_PREINSTALL_CARLA is not set to 'true' or 'false' (current value: '${DEMO_BUILD_PREINSTALL_CARLA:-<unset>}'). Proceeding with CARLA installation..."
fi

## 1. User Confirmation Prompt
echo -e "${YELLOW}--- CARLA & Extra Maps Installation Plan ---${NC}"
echo -e "CARLA Version   : ${CARLA_VERSION}"
echo -e "Target Directory: ${INSTALL_DIR}"
echo ""

if [ "$SKIP_LICENSE_AGREEMENT" != true ]; then
  read -p "Required for installation: Do you accept Unreal Engine's EULA? (https://www.unrealengine.com/eula/unreal) (Y/n) " -n 1 -r
  echo
  if [[ -n "$REPLY" && ! "$REPLY" =~ ^[Yy]$ ]]; then
    warn "Unreal Engine EULA was not accepted. Aborting installation."
    exit 1
  fi
fi

## 2. CARLA Binary Installation
if [ ! -d "$INSTALL_DIR" ]; then
  log "Downloading CARLA ${CARLA_VERSION} (16GB+)..."
  mkdir -p "$INSTALL_DIR"
  curl -L "$CARLA_URL" -o "$ARCHIVE_NAME"

  log "Extracting CARLA to ${INSTALL_DIR}..."
  tar -xzf "$ARCHIVE_NAME" -C "$INSTALL_DIR"
  rm -f "$ARCHIVE_NAME"
  log "CARLA ${CARLA_VERSION} binaries installed successfully to ${INSTALL_DIR}."
else
  warn "CARLA directory already exists at ${INSTALL_DIR}. Skipping base download."
fi

## 3. Additional Maps Installation (Town15, etc.)
if [ ! -d "$INSTALL_DIR/CarlaUE4/Content/Carla/Maps/${CARLA_MAP}" ]; then
  mkdir -p "$INSTALL_DIR/Import"
  MAPS_ARCHIVE_PATH="$INSTALL_DIR/Import/$MAPS_FILENAME"

  if [ ! -f "$MAPS_ARCHIVE_PATH" ]; then
    log "Downloading additional maps (${CARLA_MAP})..."
    curl -L "$MAPS_URL" -o "$MAPS_ARCHIVE_PATH"
  fi

  log "Extracting additional maps to ${INSTALL_DIR}..."
  tar -xzf "$MAPS_ARCHIVE_PATH" -C "$INSTALL_DIR"
  rm -f "$MAPS_ARCHIVE_PATH"
  log "Additional maps installed successfully."
else
  log "Additional maps (${CARLA_MAP}) already exist in ${INSTALL_DIR}. Skipping maps download."
fi

echo -e "Next steps:"
echo -e "1. Set up SOME/IP bridge : ${GREEN}cd ../../someip-bridge && ./setup_someip_bridge.sh${NC}"
echo -e "2. Run simulation         : ${GREEN}cd ../../someip-bridge && ./run_carla_and_bridge.sh --mode=manual-wasd${NC}"
