#!/bin/bash -eu
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

# Installs observal_cli and observal_shared plus their runtime dependencies.
pip3 install --no-cache-dir .

# The FastAPI server is not packaged; it is imported from the tree, exactly as
# tests/conftest.py does. PyInstaller needs the same path to resolve `services`.
# observal_shared reads its model catalogue with importlib.resources, so those
# JSON files have to be collected explicitly.
FUZZ_DIR="$SRC/observal/fuzz"
SERVER_DIR="$SRC/observal/observal-server"

for fuzzer in "$FUZZ_DIR"/*_fuzzer.py; do
  target="$(basename -s .py "$fuzzer")"

  compile_python_fuzzer "$fuzzer" --paths="$SERVER_DIR" --collect-data=observal_shared

  if [[ -d "$FUZZ_DIR/corpus/$target" ]]; then
    zip -j "$OUT/${target}_seed_corpus.zip" "$FUZZ_DIR/corpus/$target"/*
  fi

  if [[ -f "$FUZZ_DIR/dictionaries/${target}.dict" ]]; then
    cp "$FUZZ_DIR/dictionaries/${target}.dict" "$OUT/${target}.dict"
  fi
done
