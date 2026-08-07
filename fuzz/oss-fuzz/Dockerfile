# SPDX-FileCopyrightText: 2026 RAWx18 <rawx18.dev@gmail.com>
# SPDX-License-Identifier: Apache-2.0

# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
################################################################################
#
# SPDX-FileCopyrightText: 2026 RAWx18 <rawx18.dev@gmail.com>
# SPDX-License-Identifier: Apache-2.0

# OSS-Fuzz rebuilds its base images continuously, so projects always use them untagged.
# hadolint ignore=DL3006
FROM gcr.io/oss-fuzz-base/base-builder-python

RUN git clone --depth 1 https://github.com/Observal/Observal.git observal
WORKDIR $SRC/observal

# session_structure_fuzzer builds its inputs with Hypothesis strategies.
RUN pip3 install --no-cache-dir hypothesis

COPY build.sh $SRC/
