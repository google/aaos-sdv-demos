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

variable "CICD_FOUNDATION_REF" {
  default = "6e656b5cd6f9c72a7b0d19ec8eaf489437d7be99"
}

variable "CICD_WORKSTATIONS_DIR" {
  default = "https://github.com/GoogleCloudPlatform/cicd-foundation.git#${CICD_FOUNDATION_REF}:apps/workstations"
}

variable "GCP_REGION" {
  default = "europe-west4"
}

variable "IMAGE" {
  default = "europe-west4-docker.pkg.dev/cloud-bigtable-automotive/sdv-images/sdv-asfp-carla-latest:latest"
}

variable "CACHE_REPO" {
  default = "europe-west4-docker.pkg.dev/cloud-bigtable-automotive/sdv-images/sdv-buildcache"
}

group "default" {
  targets = ["sdv-demos"]
}

target "preflight" {
  context    = "${CICD_WORKSTATIONS_DIR}"
  dockerfile = "preflight/Dockerfile"
}

target "common" {
  context    = "${CICD_WORKSTATIONS_DIR}/common"
  dockerfile = "Dockerfile"
  args = {
    PREFLIGHT_IMAGE = "preflight"
  }
  contexts = {
    preflight = "target:preflight"
  }
}

target "remote-desktop" {
  context    = "${CICD_WORKSTATIONS_DIR}/remote-desktop"
  dockerfile = "Dockerfile"
  args = {
    BASE_IMAGE              = "common"
    GCP_REGION              = "${GCP_REGION}"
    INSTALL_GUACAMOLE       = "false"
    DEFAULT_CLIENT_PROTOCOL = "HTTP"
    SUPPORTED_PROTOCOLS     = "HTTP,SSH"
    BACKEND_PROXY_PATH      = "/selkies/"
  }
  contexts = {
    common = "target:common"
  }
}

# Wire android-studio-for-platform directly onto remote-desktop, skipping the gnome layer.
target "asfp" {
  context    = "${CICD_WORKSTATIONS_DIR}/android-studio-for-platform"
  dockerfile = "Dockerfile"
  args = {
    BASE_IMAGE = "remote-desktop"
    GCP_REGION = "${GCP_REGION}"
    AOSP_PKGS  = "bison build-essential curl flex fontconfig git-core gnupg lib32z1-dev libc6-dev-i386 libgl1-mesa-dev libncurses6 libx11-dev libxml2-utils repo rsync unzip x11proto-core-dev xsltproc zip zlib1g-dev"
  }
  contexts = {
    remote-desktop = "target:remote-desktop"
  }
}

target "sdv-demos" {
  context    = "."
  dockerfile = "docker/Dockerfile"
  tags       = ["${IMAGE}"]
  args = {
    BASE_IMAGE = "asfp"
  }
  contexts = {
    asfp = "target:asfp"
  }
  cache-from = [
    "type=registry,ref=${CACHE_REPO}:latest"
  ]
  cache-to = [
    "type=registry,ref=${CACHE_REPO}:latest,mode=min"
  ]
}
