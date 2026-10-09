<!--
Copyright 2026 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# SDV Workstation Image (cicd-foundation ASfP Base)

This directory provides the modern **Software Defined Vehicle (SDV)** Cloud Workstations container image layered directly on top of Google's [cicd-foundation Android Studio for Platform (ASfP)](https://github.com/GoogleCloudPlatform/cicd-foundation/tree/main/apps/workstations/android-studio-for-platform) blueprint.

---


### The base layer chain

The image is built via BuildKit (`docker/docker-bake.hcl` and `docker/Dockerfile`) across `cicd-foundation` and `sdv-demos`, wiring `android-studio-for-platform` directly onto `remote-desktop` (`INSTALL_GUACAMOLE=false`) and skipping the `gnome` layer:

```
cloud-workstations predefined/base
  └── preflight + common   Cloud Workstations systemd contract & preflight UI
        └── remote-desktop (INSTALL_GUACAMOLE=false)   nginx, Chrome, openssh
              └── android-studio-for-platform   ASfP canary, Cuttlefish
                    └── sdv-asfp-carla-latest   (docker/Dockerfile in this repo)
```

By re-wiring the build graph with `docker buildx bake`:
- **The `gnome` layer is completely omitted**: `ubuntu-desktop-minimal`, Mutter, GNOME Shell 46, `gnome-remote-desktop`, and `layer_readiness_probe.sh` are never installed.
- **Guacamole is disabled at build time** (`INSTALL_GUACAMOLE=false`): `guacd.tar` and `guacamole.tar` are never fetched or bundled.
- **Desktop & readiness configuration is baked in at build time**: `docker/systemd/multi-user.target.d/20-desktop.conf`, `docker/systemd/backend-readiness.service.d/20-sdv.conf`, and masking `audio-streamer.service` (which otherwise binds port `8081`) happen during `docker buildx bake` rather than in a runtime startup script.

### What comes from the `cicd-foundation` base layers (`common` + `remote-desktop` + `asfp`):
- **IDE**: Android Studio for Platform (ASfP Canary) pre-configured with memory options and desktop autostart.
- **Android Virtualization**: Cuttlefish Android emulator pre-compiled for the kernel with `kvm`, `cvdnetwork`, and `render` permissions.
- **AOSP Build Toolchain**: `repo`, `bison`, `flex`, `build-essential`, and required build libraries.
- **Hardware Acceleration**: Automatic GPU detection (`WORKSTATION_GPU_ENABLED`) with NVIDIA Container Toolkit (CDI).
- **Systemd contract**: entrypoint, `workstation-startup.d` hook runner, user setup, nginx, backend readiness, preflight UI.

### What this derived layer adds (`sdv-asfp-carla-latest`):
- **Desktop & streaming stack**: a plain headless X server (Xtigervnc on `:0`) with `openbox` for window management and `tint2` for a panel, captured by **Selkies 2.x** and encoded on the T4's **NVENC**.
- **Python 3.7.17 Isolated Environment**: In `/opt/python3.7` with CARLA `0.9.15`, `someipy`, `pygame`, and `protobuf`.
- **CARLA Utilities**: `/google/carla915-utils/setup_carla.sh` (copied from `build-utils/carla915-utils/`) and environment path hooks.
- **SOME/IP Bridge**: `/google/someip-bridge/` scripts and client logic for vehicle simulation.
- **AAOS & Recipe Utilities**: `/google/aaos-utils/` and `/google/recipe/base.sh` (copied from `build-utils/aaos-utils/` and `build-utils/recipe/`) for checkout, building, and patching Android Automotive OS.
- **Antigravity IDE**: Extracted to `/opt/Antigravity-x64`, auto-started on the left 40% of the desktop via `sdv-antigravity.service`, and accessible at runtime via `antigravity-ide`.

---

## 🖥️ Desktop stack

```
CARLA (GPU, offscreen) → manual_control.py (pygame) → Xtigervnc :0
                                                        ↑ openbox + tint2
                                                        ↓ XShm capture
                                          Selkies → NVENC → nginx :8081 → browser
```

No compositor sits in the video path. Mutter's headless backend has no route to
the Tesla T4 (NVIDIA's EGL lacks `EGL_MESA_platform_surfaceless` and Mesa has no
T4 driver), so a GNOME session composites on llvmpipe at roughly 5.2 cores.

Xtigervnc is used rather than Xvfb because it supports RandR resizing at runtime,
which is what makes Selkies' dynamic resolution work. **Nothing connects over the
VNC protocol.**

The stack runs as systemd units under `sdv-desktop.target`
(`docker/systemd/`), so it is supervised (`Restart=always`) and logs to the
journal:

```bash
systemctl status sdv-desktop.target
journalctl -u sdv-selkies -f
```

`tint2` runs on stock defaults, and `/etc/xdg/openbox/rc.xml` includes window
placement rules that snap Antigravity IDE to the left 40% of the screen and
place the initial SDV Terminal on the right side.

---

## 🚀 Building the Image

```bash
BUILDX_BAKE_ENTITLEMENTS_FS=0 docker buildx bake -f docker/docker-bake.hcl sdv-demos --push
```

Or via the Cloud Build pipeline in `sdv-setup`:

```bash
~/Workspace/sdv-setup/pipelines/build_cloud.sh --stop-before-compilation
```
