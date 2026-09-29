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

set -eo pipefail

# Dynamic NVIDIA driver & library integration (Cloud Workstations mounts /var/lib/nvidia at runtime)
if [[ -d "/var/lib/nvidia" ]]; then
  # 1. Symlink NVIDIA host binaries
  if [[ -d "/var/lib/nvidia/bin" ]]; then
    ln -sf /var/lib/nvidia/bin/* /usr/local/bin/ 2> /dev/null || true
  fi

  # 2. Dynamic Linker Configuration (PATH and LD_LIBRARY_PATH handled by default_envs.sh)
  mkdir -p /etc/ld.so.conf.d
  printf "/var/lib/nvidia/lib64\n/var/lib/nvidia/lib\n" > /etc/ld.so.conf.d/nvidia.conf
  ldconfig /var/lib/nvidia/lib64 /var/lib/nvidia/lib 2> /dev/null || ldconfig 2> /dev/null || true

  # 3. Vulkan & GLVND ICD Configuration
  mkdir -p /etc/vulkan/icd.d /usr/share/glvnd/egl_vendor.d /etc/glvnd/egl_vendor.d
  cat << 'ICD_EOF' > /etc/vulkan/icd.d/nvidia_icd.json
{
    "file_format_version" : "1.0.0",
    "ICD": {
        "library_path": "libGLX_nvidia.so.0",
        "api_version" : "1.3.277"
    }
}
ICD_EOF
  cat << 'GLVND_EOF' > /usr/share/glvnd/egl_vendor.d/10_nvidia.json
{
    "file_format_version" : "1.0.0",
    "ICD" : {
        "library_path" : "libEGL_nvidia.so.0"
    }
}
GLVND_EOF
  cp -f /usr/share/glvnd/egl_vendor.d/10_nvidia.json /etc/glvnd/egl_vendor.d/10_nvidia.json
fi
