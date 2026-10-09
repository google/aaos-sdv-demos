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

# Set of env variables that control demo installation, and runtime behaviour.
# Optionally, `source base.sh` before deploying demo.
# Main intended usage: deploying demo in CI pipelines

export DEMO_BUILD_BRANCH="android-latest-release"
export DEMO_BUILD_WITH_GAS="false" # WIP
export DEMO_BUILD_CARLA_VERSION="0.9.15"
export DEMO_BUILD_AAOS_PATCHES="base|sdv-nexus|ivi-no-gas-extra"
export DEMO_BUILD_CARLA_MAP="Town15"
export DEMO_BUILD_PREINSTALL_CARLA="true"
