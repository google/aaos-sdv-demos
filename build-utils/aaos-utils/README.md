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

# Open-Source AAOS Deployment Utilities

This directory contains automation scripts and patch tools for checking out, patching, building, and deploying the **AAOS 26Q2** Software-Defined Vehicle (SDV) environment.

---

## Directory Overview

```text
build-utils/aaos-utils/
├── README.md                           # Documentation
├── checkout_aaos.sh                    # Syncs AAOS source tree from AOSP manifests
├── dev_utils.sh                        # Shell utilities for building & launching CVDs
├── deploy_aaos_26q2_entry_point.sh     # Master end-to-end deployment entry point
└── patch_applier/
    ├── patch_aaos.py                   # Executable Python patch validator & applier
    ├── patches.json                    # JSON manifest specifying patches & base SHAs
    └── patches/                        # Directory containing git diff patch files
        ├── device_google_sdv.patch
        ├── packages_services_display_safety.patch
        ├── sdv_device_add_default_gateway.patch
        ├── system_software_defined_vehicle_samples.patch
        ├── system_software_defined_vehicle_vsidl.patch
        └── system_software_defined_vehicle_vsidl_apex_key.patch
```

---

## Quick Start

### 1. End-to-End Automated Deployment
Run the master entry point script to checkout source, apply custom SDV patches, build images, and load development utilities:

```bash
source ./deploy_aaos_26q2_entry_point.sh
```

---

## Utility Scripts Usage

### `checkout_aaos.sh`
Syncs the open-source AAOS repositories using `repo`:
```bash
./checkout_aaos.sh [OPTIONS]

Options:
  -o, --output-dir   Directory for AOSP checkout (default: ~/Workspace/aaos-26q2)
  -u, --repo-url     Manifest repo URL
  -b, --branch       Manifest branch/tag (default: android-latest-release)
  -j, --threads      Sync thread count (default: 20)
```

---

### `patch_applier/patch_aaos.py`
Validates manifest entries, filters by tag, orders multiple patches per repository, and applies and commits diff patches across target repositories:
```bash
./patch_applier/patch_aaos.py --aaos-dir ~/Workspace/aaos-26q2 --patch-tag-filter="base|sdv-nexus"
```

#### Manifest Format (`patches.json`)
```json
[
  {
    "repo_path": "device/google/sdv",
    "patch_filename": "patches/device_google_sdv.patch",
    "description": "Add carla client as service, car controller SB",
    "tag": "base",
    "patch_ordering": 0
  }
]
```

---

### `dev_utils.sh`
Source `dev_utils.sh` in your shell (or `~/.bashrc`) to gain access to building and Cuttlefish management commands:

```bash
source dev_utils.sh

# Build both SDV Media and IVI lunch targets
build

# Launch dual-CVD instances using cvd load
launch_2vm

# Stop / reset running CVD instances
clear_2vm
```

