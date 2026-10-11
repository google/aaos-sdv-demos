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

set -euo pipefail

# Forward AGY_ADC_AUTH and GOOGLE_CLOUD_* from Terraform container.env
# to /etc/profile.d/agy-env.sh, /etc/environment, and systemd DefaultEnvironment
# before /sbin/init replaces PID 1's environment.
env_vars=()
rm -f /etc/profile.d/agy-env.sh /etc/systemd/system.conf.d/20-agy-env.conf

for var in AGY_ADC_AUTH GOOGLE_CLOUD_PROJECT GOOGLE_CLOUD_QUOTA_PROJECT; do
  if [[ -n "${!var:-}" ]]; then
    env_vars+=("\"${var}=${!var}\"")
    if [[ -f /etc/environment ]]; then
      sed -i "/^${var}=/d" /etc/environment
    fi
    echo "${var}=\"${!var}\"" >> /etc/environment
    # shellcheck disable=SC2016
    printf 'export %s="${%s-%s}"\n' "${var}" "${var}" "${!var}" >> /etc/profile.d/agy-env.sh
  fi
done

if (( ${#env_vars[@]} > 0 )); then
  chmod 644 /etc/profile.d/agy-env.sh
  mkdir -p /etc/systemd/system.conf.d
  printf "[Manager]\nDefaultEnvironment=%s\n" "${env_vars[*]}" \
    > /etc/systemd/system.conf.d/20-agy-env.conf
fi
