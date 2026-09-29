/*
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/*
 * No-op ABI stub for libx264 (SONAME: libx264-03b89520.so.165).
 *
 * Why:
 *   The upstream Selkies 2.0 (pixelflux) wheel bundles a GPLv2+ libx264 shared
 *   library for software CPU H.264 fallback encoding. Because the SDV Cloud
 *   Workstation exclusively uses NVIDIA Tesla T4 hardware encoding (h264_nvenc
 *   via LGPLv2.1+ libavcodec), libx264 is never invoked at runtime. Replacing
 *   the bundled libx264 binary with this Apache-2.0 stub satisfies dynamic
 *   linker symbol resolution while removing GPLv2+ x264 code from the published
 *   container image.
 */

#include <stddef.h>

void *x264_encoder_open_165(void *params) {
  (void)params;
  return NULL;
}

void x264_encoder_close(void *encoder) {
  (void)encoder;
}

int x264_encoder_encode(void *encoder, void **nal, int *i_nal, void *pic_in,
                        void *pic_out) {
  (void)encoder;
  (void)nal;
  (void)i_nal;
  (void)pic_in;
  (void)pic_out;
  return -1;
}

void x264_encoder_parameters(void *encoder, void *params) {
  (void)encoder;
  (void)params;
}

int x264_encoder_reconfig(void *encoder, void *params) {
  (void)encoder;
  (void)params;
  return 0;
}

int x264_param_apply_profile(void *params, const char *profile) {
  (void)params;
  (void)profile;
  return 0;
}

int x264_param_default_preset(void *params, const char *preset,
                              const char *tune) {
  (void)params;
  (void)preset;
  (void)tune;
  return 0;
}

void x264_picture_init(void *pic) {
  (void)pic;
}
