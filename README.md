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

# SDV Demos

Repository containing tools, bridges, and deployment scripts for Software Defined Vehicle (AAOS-SDV) demonstrations and AAOS-IVI integrations.

---

## Directory Overview

* **`build-utils/`**: Build and deployment utilities for the demo environment:
  * **`aaos-utils/`**: Deployment and patching scripts for checking out, patching, and building the open-source AAOS 26Q2 demo.
  * **`carla915-utils/`**: Utilities for downloading, installing, and managing CARLA 0.9.15 simulator binaries and additional maps.
  * **`recipe/`**: Environment configuration presets (`base.sh`) controlling demo installation and runtime parameters.
* **`car-controller/`**: Source code for car-controller APEX, aaos-26q2 compatible.
* **`someip-bridge/`**: Python SOME/IP bridge service, environment setup scripts, network configurations, remote execution helpers, and CARLA client control scripts.
* **`docker/`**: Container configurations (`docker/Dockerfile`, `docker/docker-bake.hcl`) and Cloud Workstation definitions.

## System requirements

* Tested on GCP n1-standard-32 with Nvidia Tesla T4 GPU workstations.
