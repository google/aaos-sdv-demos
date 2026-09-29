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
PYTHON_VERSION="3.7.17"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSUME_YES=false
WITH_PYENV=false

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y | --yes)
      ASSUME_YES=true
      shift
      ;;
    --with-pyenv)
      WITH_PYENV=true
      shift
      ;;
    -h | --help)
      echo "Usage: $(basename "$0") [-y|--yes] [--with-pyenv]"
      echo "  -y, --yes     Non-interactive mode (assume yes to prompts)"
      echo "  --with-pyenv  Install pyenv, build Python 3.7 from source, and create a virtual environment"
      exit 0
      ;;
    *)
      shift
      ;;
  esac
done

cd "${SCRIPT_DIR}"

## 1. User Confirmation Prompt
echo -e "${YELLOW}--- SOME/IP Bridge Environment Setup Plan ---${NC}"
echo -e "Target Directory : ${SCRIPT_DIR}"
echo -e "Use Pyenv & venv : ${WITH_PYENV}"
echo ""

if [ "$ASSUME_YES" != true ]; then
  read -p "Do you want to proceed with this check/setup? (y/N): " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log "Setup aborted by user."
    exit 0
  fi
fi

if [ "$WITH_PYENV" = true ]; then
  ## 2. Dependencies & Pyenv Setup
  if [ -d "/opt/pyenv" ]; then
    export PYENV_ROOT="/opt/pyenv"
  else
    export PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}"
  fi

  if [ -d "$PYENV_ROOT/bin" ]; then
    export PATH="$PYENV_ROOT/bin:$PATH"
  fi

  if ! command -v pyenv &> /dev/null; then
    log "Ensuring system dependencies are present (pyenv)..."
    sudo apt-get update -qq
    sudo apt-get install -y make build-essential libssl-dev zlib1g-dev \
      libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm \
      libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev \
      pyenv > /dev/null || true
  fi

  ## 2.1. Pyenv init
  if ! command -v pyenv &> /dev/null; then
    warn "Failed to find pyenv. Exiting early."
    exit 1
  fi

  # Initialize pyenv for this session (both path and shims)
  eval "$(pyenv init --path)"
  eval "$(pyenv init -)"

  if ! grep -q 'pyenv init' "$HOME/.bashrc" 2> /dev/null; then
    log "Configuring pyenv in .bashrc..."
    {
      echo "export PYENV_ROOT=\"${PYENV_ROOT}\""
      # shellcheck disable=SC2016
      echo '[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"'
      # shellcheck disable=SC2016
      echo 'eval "$(pyenv init - bash)"'
    } >> "$HOME/.bashrc"
  fi

  ## 3. Python Environment Setup via Pyenv
  log "Setting up Python ${PYTHON_VERSION} in ${SCRIPT_DIR} via pyenv..."
  pyenv install -s "$PYTHON_VERSION"
  pyenv local "$PYTHON_VERSION"
  pyenv rehash

  # Diagnostics
  log "Diagnostic: pyenv version: $(pyenv version)"
  log "Diagnostic: which python: $(pyenv which python)"
  log "Diagnostic: python --version: $(python --version)"

  PYTHON_BIN="$(pyenv which python)"

  ## 4. Virtual Environment Creation & Dependencies Installation
  log "Creating virtual environment '.venv' using ${PYTHON_BIN}..."
  "$PYTHON_BIN" -m venv .venv
  # shellcheck source=/dev/null
  source .venv/bin/activate

  log "Installing Python dependencies from requirements.txt with hash verification..."
  ./.venv/bin/pip install --require-hashes --ignore-requires-python -r requirements.txt --index-url https://pypi.org/simple --disable-pip-version-check
  cp "${SCRIPT_DIR}/sitecustomize.py" ./.venv/lib/python3.7/site-packages/sitecustomize.py

  log "Success! SOME/IP Bridge environment is ready with virtual environment."
  echo -e "Next steps:"
  echo -e "1. Activate venv  : ${GREEN}source .venv/bin/activate${NC}"
  echo -e "2. Run bridge     : ${GREEN}./run_carla_and_bridge.sh --mode=manual-wasd${NC}"
else
  ## Check if system is correctly provisioned (e.g. inside container)
  PYTHON_BIN=""
  if command -v python3.7 > /dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.7)"
  elif [ -x "/opt/python3.7/bin/python3.7" ]; then
    PYTHON_BIN="/opt/python3.7/bin/python3.7"
  elif [ -x "/usr/local/bin/python3.7" ]; then
    PYTHON_BIN="/usr/local/bin/python3.7"
  fi

  if [ -n "$PYTHON_BIN" ] && "$PYTHON_BIN" -c "import carla, someipy, pygame, numpy" > /dev/null 2>&1; then
    log "System is correctly provisioned with Python 3.7 and required dependencies."
    log "Environment is ready! (No virtual environment or pyenv needed)."
    echo -e "Next step:"
    echo -e "Run bridge: ${GREEN}./run_carla_and_bridge.sh --mode=manual-wasd${NC}"
    exit 0
  else
    warn "System not correctly provisioned. Are you not using containerised demo? Run --with-pyenv to provision system"
    exit 1
  fi
fi
