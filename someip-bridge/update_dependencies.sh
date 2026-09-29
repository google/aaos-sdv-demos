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

# update_dependencies.sh
# Automates the generation of hashed requirements.txt from requirements.in using 'hashin'.
# This script ensures a "trusted base" by first installing hashed remediation tools.
# Usage: ./update_dependencies.sh [requirements.in]

set -eo pipefail

# 1. Configuration & Input Validation
REQ_IN="${1:-requirements.in}"
REQ_TXT="requirements.txt"
BASE_TOOLING_TXT="base-tooling-requirements.txt"
VENV_DIR=".dep_update_venv"

if [[ ! -f "$REQ_IN" ]]; then
  echo "[ERROR] $REQ_IN not found."
  exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "[INFO] Detected Python version: $PYTHON_VERSION"

if [[ "$PYTHON_VERSION" != "3.7" ]]; then
  echo "[ERROR] This project strictly requires Python 3.7. (Detected: $PYTHON_VERSION)"
  echo "        Please ensure python3 refers to a 3.7 interpreter before running."
  exit 1
fi

# 2. Prepare base tooling with hashes (Establishing a Trusted Base)
echo "[INFO] Creating base-tooling-requirements.txt for Python 3.7"
cat > "$BASE_TOOLING_TXT" <<- EOF
pip==23.1.2 \
    --hash=sha256:0e7c86f486935893c708287b30bd050a36ac827ec7fe5e43fe7cb198dd835fba \
    --hash=sha256:3ef6ac33239e4027d9a5598a381b9d30880a1477e50039db2eac6e8a8f6d1b18
setuptools==68.0.0 \
    --hash=sha256:11e52c67415a381d10d6b462ced9cfb97066179f0e871399e006c4ab101fc85f \
    --hash=sha256:baf1fdb41c6da4cd2eae722e135500da913332ab3f2f5c7d33af9b492acb5235
hashin==0.17.0 \
    --hash=sha256:4c03b3b1520a5117d8fdc26ae83c1267bc40da9925cd89b56b437bcb02bebb53 \
    --hash=sha256:baa00fe209ee6800a7d09ffa3198b31d71ab1503730e7c172b7eccd01b6ec47e
packaging==24.0 \
    --hash=sha256:2ddfb553fdf02fb784c234c7ba6ccc288296ceabec964ad2eae3777778130bc5 \
    --hash=sha256:eb82c5e3e56209074766e6885bb04b8c38a0c015d0a30036ebe7ece34c9989e9
pip-api==0.0.33 \
    --hash=sha256:1c2522ae21efcb034d89cc99f6cf1025293b31c63c29ee98b23f03a85f36bdae \
    --hash=sha256:b8d6eb5a87d3a9e112a20a8e9d24a6fc12d4e1c94d7595eeaf74be11ad47276c
EOF

# 3. Setup temporary virtual environment
echo "[INFO] Creating temporary virtual environment ($VENV_DIR)..."
python3 -m venv "$VENV_DIR"
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

# 4. Install verified remediation tooling using hashes
echo "[INFO] Installing verified tooling from trusted base..."
pip install --require-hashes -r "$BASE_TOOLING_TXT" --index-url https://pypi.org/simple

# 5. Generate hashed requirements.txt directly from requirements.in
echo "[INFO] Generating $REQ_TXT with hashes via hashin..."
rm -f "$REQ_TXT"
touch "$REQ_TXT"

# Read requirements.in, filter comments/empty lines, and run hashin for each
grep -E -v '^(#|$)' "$REQ_IN" | while read -r dep; do
  echo "[INFO] Hashing $dep..."
  hashin "$dep" -r "$REQ_TXT" --python-version 3.7
done

# 6. Cleanup
echo "[INFO] Cleaning up..."
deactivate
rm -rf "$VENV_DIR"
rm -f "$BASE_TOOLING_TXT"

echo "[SUCCESS] $REQ_TXT generated with hashes."
