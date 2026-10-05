# syntax=docker/dockerfile:1.4

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

# ==============================================================================
# Software Defined Vehicle (SDV) Cloud Workstation Image
#
# Base: Android Studio for Platform (ASfP) Custom Workstation Image from
#       GoogleCloudPlatform/cicd-foundation, built via BuildKit (docker/docker-bake.hcl)
#       directly atop remote-desktop (INSTALL_GUACAMOLE=false), skipping the gnome layer.
#
# Additions:
#   - Standalone Python 3.7.17 environment with CARLA 0.9.15 and SOME/IP bindings
#   - CARLA simulator 0.9.15 setup & management utilities
#   - SOME/IP bridge and client orchestration scripts
#   - AAOS (Android Automotive OS) latest release demo & patching utilities
#   - Remote desktop stack: X11 + openbox + tint2 + Selkies NVENC H.264
# ==============================================================================

ARG BASE_IMAGE

FROM ${BASE_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive
ENV NVIDIA_VISIBLE_DEVICES=all
# OPTIMISATION: Expose NVIDIA hardware video encoder (libnvidia-encode.so) for Selkies NVENC H.264 streaming
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics,display,video
# Declare an HTTP backend and route Cloud Workstations / preflight redirects directly
# to Selkies instead of Guacamole RDP-over-Tomcat.
ENV BACKEND_PROXY_PATH="/selkies/"
ENV DEFAULT_CLIENT_PROTOCOL=HTTP
ENV SUPPORTED_PROTOCOLS="HTTP,SSH"
ENV DEFAULT_REDIRECT_PATH="/selkies/"

# Packages required by CARLA 0.9.15 simulation runtime (Vulkan rendering, OpenMP)
# and by image verification tests.
#
# NOTE: `bats` is intentionally installed even though this repository contains no
# .bats files: the test suites live in an external CI pipeline that runs against
# this image. Do not remove it.
ARG CARLA_RUNTIME_PKGS="\
  bats \
  libomp5 \
  vulkan-tools"

# Packages for the remote desktop stack.
#
# Architecture: Selkies captures a plain headless X server (DISPLAY=:0) via XShm
# and encodes with NVENC. openbox provides window management; tint2 provides a
# minimal panel.
#
# Xtigervnc is used as the X server rather than Xvfb because it supports RandR
# resizing at runtime, which is what makes Selkies' dynamic resolution work.
# Nothing connects over the VNC protocol.
#
# Why no compositing desktop: Mutter's headless backend has no path to the Tesla
# T4 (NVIDIA's EGL lacks EGL_MESA_platform_surfaceless and Mesa has no T4 driver),
# so GNOME falls back to llvmpipe and burns ~5.2 cores compositing. Selkies also
# always owns its own display server and has no PipeWire/portal capture path
# (https://github.com/selkies-project/selkies/issues/46), so a compositor in the
# video path can only ever be an extra hop.
ARG SELKIES_DEB_URL="https://github.com/selkies-project/selkies/releases/download/2.0.0rc0/selkies-2.0.0rc0-ubuntu24.04-amd64.deb"
ARG SELKIES_STACK_PKGS="\
  gnome-terminal \
  openbox \
  tigervnc-standalone-server \
  tint2 \
  x11-xserver-utils"

# 1a. Install CARLA runtime dependencies and the BATS test harness
RUN apt-get update && \
    apt-get install -y --no-install-recommends ${CARLA_RUNTIME_PKGS} && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 1b. Download and install the Selkies NVENC H.264 streaming stack
RUN curl -fsSL -o /tmp/selkies.deb "${SELKIES_DEB_URL}" && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      ${SELKIES_STACK_PKGS} \
      /tmp/selkies.deb && \
    rm -f /tmp/selkies.deb && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 1c. Override the base image's Google Chrome wrapper, remove the Wayland
# ASfP Studio wrapper (replaced by the `asfp` bash function), and install the
# Selkies launcher.
#
# Both base wrappers hardcode Wayland, and asfp-studio additionally calls
# wait_for_monitor(), which polls org.gnome.Mutter.DisplayConfig - with GNOME
# masked that can never succeed and costs a 60s stall on every launch.
COPY --chmod=755 docker/scripts/bin/ /usr/local/bin/
RUN rm -f /usr/local/bin/asfp-studio

# Bypass the wrapper that assumes a wayland system.
RUN ln -sf /usr/local/bin/google-chrome-stable /usr/local/bin/google-chrome

# 2. Standalone Python 3.7 environment with CARLA and SOME/IP dependencies
COPY --from=python:3.7-slim /usr/local /opt/python3.7
ENV PATH="${PATH}:/opt/python3.7/bin"

COPY --chmod=644 someip-bridge/sitecustomize.py /opt/python3.7/lib/python3.7/site-packages/sitecustomize.py
COPY --chmod=644 someip-bridge/requirements.txt /tmp/requirements.txt

RUN python3.7 -m pip install --no-cache-dir --ignore-requires-python --require-hashes -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# 3. CARLA 0.9.15 Setup Utilities (executed on builder workstation)
COPY --chmod=755 build-utils/carla915-utils/ /google/carla915-utils/

# 4. SOME/IP Bridge & Client Utilities
COPY --chmod=644 someip-bridge/carla_someip_client.py /google/someip-bridge/carla_someip_client.py
COPY --chmod=644 someip-bridge/get_data_logic.py /google/someip-bridge/get_data_logic.py
COPY --chmod=755 someip-bridge/run_carla_and_bridge.sh /google/someip-bridge/run_carla_and_bridge.sh
COPY --chmod=644 someip-bridge/external_utils/manual_control.py /google/someip-bridge/external_utils/manual_control.py

# 5. AAOS Demo Utilities (Latest Release)
COPY --chmod=644 build-utils/recipe/base.sh /google/recipe/base.sh
COPY --chmod=755 build-utils/aaos-utils/checkout_aaos.sh /google/aaos-utils/checkout_aaos.sh
COPY --chmod=755 build-utils/aaos-utils/deploy_aaos_26q2_entry_point.sh /google/aaos-utils/deploy_aaos_26q2_entry_point.sh
COPY --chmod=644 build-utils/aaos-utils/dev_utils.sh /google/aaos-utils/dev_utils.sh
COPY --chmod=644 build-utils/aaos-utils/ds-multi-cvd-config.json /google/aaos-utils/ds-multi-cvd-config.json
COPY --chmod=755 build-utils/aaos-utils/patch_applier/patch_aaos.py /google/aaos-utils/patch_applier/patch_aaos.py
COPY --chmod=644 build-utils/aaos-utils/patch_applier/patches.json /google/aaos-utils/patch_applier/patches.json
COPY --chmod=644 build-utils/aaos-utils/patch_applier/patches/ /google/aaos-utils/patch_applier/patches/

# 6. SDV Utility Scripts, Nginx Config, Startup Hooks and Desktop Units
#    (NVIDIA setup & X11 + openbox + tint2 + Selkies NVENC desktop setup)
COPY --chmod=644 docker/nginx/default.template /etc/nginx/sites-available/default.template
COPY --chmod=644 docker/nginx/conf.d/ /etc/nginx/conf.d/
COPY --chmod=755 docker/scripts/workstation-startup.d/ /etc/workstation-startup.d/
COPY --chmod=644 docker/systemd/ /etc/systemd/system/
COPY --chmod=644 docker/scripts/sdv-bashrc-hook/ /google/sdv-bashrc-hook/
# Override the base image's user_setup.sh.
COPY --chmod=751 docker/scripts/google/user_setup.sh /google/scripts/user_setup.sh
RUN chmod 755 /etc/systemd/system/multi-user.target.d \
              /etc/systemd/system/backend-readiness.service.d \
              /google/someip-bridge \
              /google/someip-bridge/external_utils \
              /google/recipe \
              /google/aaos-utils/patch_applier/patches \
              /google/sdv-bashrc-hook && \
    rm -f /etc/systemd/system/multi-user.target.wants/audio-streamer.service && \
    ln -sf /dev/null /etc/systemd/system/audio-streamer.service

RUN echo "source /google/sdv-bashrc-hook/sdv_demo_bash_utils.sh" >> /etc/skel/.bashrc

ENTRYPOINT ["/google/scripts/entrypoint.sh"]
