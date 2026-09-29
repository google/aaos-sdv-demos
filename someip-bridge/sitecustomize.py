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

"""Python 3.7 compatibility monkeypatch for typing.Protocol and runtime_checkable."""

try:
    import typing
    import typing_extensions

    typing.Protocol = getattr(
        typing, "Protocol", getattr(typing_extensions, "Protocol", None)
    )
    typing.runtime_checkable = getattr(
        typing,
        "runtime_checkable",
        getattr(typing_extensions, "runtime_checkable", None),
    )
    typing.TypedDict = getattr(
        typing, "TypedDict", getattr(typing_extensions, "TypedDict", None)
    )
except ImportError:
    pass
