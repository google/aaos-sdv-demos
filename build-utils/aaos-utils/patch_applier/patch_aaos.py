#!/usr/bin/env python3
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

"""Patch Applier script for AAOS workspace repositories.

Reads a JSON config manifest specifying patches, tags, ordering, descriptions,
and target repository paths, filters by requested tags, applies patches in
per-repository order, and commits each applied patch.
"""

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional, Set


REQUIRED_ENTRY_FIELDS = (
    "repo_path",
    "patch_filename",
    "description",
    "tag",
    "patch_ordering",
)
REQUIRED_STR_FIELDS = ("repo_path", "patch_filename", "description", "tag")


@dataclass
class PatchTask:
    """Represents a validated patch application task."""

    patch_file: Path
    repo_dir: Path
    repo_rel: str
    description: str
    tag: str
    patch_ordering: int


def log_error(msg: str) -> None:
    """Prints diagnostic error message to stderr."""
    sys.stderr.write(f"ERROR: {msg}\n")


def log_info(msg: str) -> None:
    """Prints progress message to stdout."""
    sys.stdout.write(f"[PATCH-AAOS] {msg}\n")


# ==============================================================================
# JSON Entry Validation Logic
# ==============================================================================


def _resolve_and_verify_patch_file(
    patch_rel: str, entry_num: int, config_dir: Path
) -> Optional[Path]:
    """Verifies .patch extension and resolves/checks file existence on disk."""
    if not patch_rel.endswith(".patch"):
        log_error(
            f"Manifest entry #{entry_num} patch_filename '{patch_rel}' "
            "must have a '.patch' extension."
        )
        return None

    patch_file = Path(patch_rel)
    if not patch_file.is_absolute():
        patch_file = (config_dir / patch_file).resolve()

    if not patch_file.is_file():
        log_error(
            f"Patch file '{patch_file}' specified for entry #{entry_num} "
            "does not exist."
        )
        return None

    return patch_file


def validate_json_entry(entry: Any, entry_num: int, config_dir: Path) -> Optional[Path]:
    """Validates a single manifest JSON entry and verifies its .patch file exists.

    Returns the resolved patch file Path if valid, or None on validation failure.
    """
    if not isinstance(entry, dict):
        log_error(f"Manifest entry #{entry_num} is not a valid JSON object.")
        return None

    missing = [
        field
        for field in REQUIRED_ENTRY_FIELDS
        if field not in entry or entry[field] is None or entry[field] == ""
    ]
    if missing:
        log_error(
            f"Manifest entry #{entry_num} is missing required fields: "
            f"{', '.join(missing)}."
        )
        return None

    for str_field in REQUIRED_STR_FIELDS:
        if not isinstance(entry[str_field], str) or not entry[str_field].strip():
            log_error(
                f"Manifest entry #{entry_num} field '{str_field}' "
                "must be a non-empty string."
            )
            return None

    ordering = entry["patch_ordering"]
    if isinstance(ordering, bool) or not isinstance(ordering, int):
        log_error(
            f"Manifest entry #{entry_num} field 'patch_ordering' " "must be an integer."
        )
        return None

    return _resolve_and_verify_patch_file(
        entry["patch_filename"].strip(), entry_num, config_dir
    )


# ==============================================================================
# Patch Application & Git Operations
# ==============================================================================


def format_commit_message(description: str) -> str:
    """Formats the standard demo base patch commit message."""
    return f"DEMO BASE PATCH\n\n{description}\n"


def is_patch_committed(repo_dir: Path, description: str) -> bool:
    """Checks if a commit with this patch's description already exists in HEAD history."""
    res = subprocess.run(
        [
            "git",
            "log",
            "--fixed-strings",
            f"--grep={description}",
            "--format=%H",
            "-n",
            "1",
        ],
        cwd=repo_dir,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return res.returncode == 0 and bool(res.stdout.strip())


def is_git_patch_applied(repo_dir: Path, patch_file: Path, description: str) -> bool:
    """Checks if a patch is already committed or applied in the working tree."""
    if is_patch_committed(repo_dir, description):
        return True

    res = subprocess.run(
        ["git", "apply", "--reverse", "--check", str(patch_file)],
        cwd=repo_dir,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return res.returncode == 0


def apply_and_commit_git_patch(
    repo_dir: Path, patch_file: Path, description: str
) -> None:
    """Applies a patch file to repo_dir index/working tree and commits it."""
    try:
        subprocess.run(
            ["git", "apply", "--index", str(patch_file)],
            cwd=repo_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as err:
        stderr_text = err.stderr.strip() if err.stderr else str(err)
        raise RuntimeError(
            f"Failed to apply patch '{patch_file}' to '{repo_dir}':\n{stderr_text}"
        ) from err

    commit_msg = format_commit_message(description)
    try:
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Demo Patch Applier",
                "-c",
                "user.email=demo-patch-applier@google.com",
                "commit",
                "-m",
                commit_msg,
            ],
            cwd=repo_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as err:
        stderr_text = err.stderr.strip() if err.stderr else str(err)
        raise RuntimeError(
            f"Failed to commit patch '{patch_file}' in '{repo_dir}':\n{stderr_text}"
        ) from err


# ==============================================================================
# Manifest Loading, Filtering & Task Ordering
# ==============================================================================


def parse_args() -> argparse.Namespace:
    """Parses and returns command line arguments."""
    parser = argparse.ArgumentParser(
        description="Applies and commits diff patches to AAOS repositories."
    )
    parser.add_argument(
        "aaos_dir_pos",
        nargs="?",
        help="Path to AAOS root deployment directory.",
    )
    parser.add_argument(
        "--aaos-dir",
        "-d",
        dest="aaos_dir_flag",
        help="Path to AAOS root deployment directory.",
    )
    parser.add_argument(
        "--config",
        "-c",
        help="Path to patches JSON manifest file (default: patches.json relative to script).",
    )
    parser.add_argument(
        "--patch-tag-filter",
        required=True,
        help="Pipe-separated list of patch tags to apply (e.g. 'TAG1|TAG2').",
    )
    return parser.parse_args()


def parse_tag_filter(raw_filter: str) -> Set[str]:
    """Parses pipe-separated tag filter string into a set of non-empty tags."""
    return {tag.strip() for tag in raw_filter.split("|") if tag.strip()}


def load_manifest(config_file: Path) -> Optional[List[Any]]:
    """Loads and returns the JSON manifest from the specified configuration file."""
    if not config_file.is_file():
        log_error(f"Patch manifest JSON file '{config_file}' not found.")
        return None

    log_info(f"Loading patch manifest: {config_file}")
    try:
        with open(config_file, "r", encoding="utf-8") as file_handle:
            manifest = json.load(file_handle)
    except (json.JSONDecodeError, OSError) as err:
        log_error(f"Failed to parse JSON manifest '{config_file}': {err}")
        return None

    if not isinstance(manifest, list):
        log_error(f"Invalid manifest format in '{config_file}': Expected a JSON array.")
        return None

    return manifest


def _order_tasks_by_repo(
    tasks_by_repo: Dict[str, List[PatchTask]]
) -> Optional[List[PatchTask]]:
    """Orders tasks per repository by patch_ordering and rejects duplicate order values."""
    ordered_tasks: List[PatchTask] = []
    for repo_rel, repo_tasks in tasks_by_repo.items():
        seen_orders: Set[int] = set()
        for task in repo_tasks:
            if task.patch_ordering in seen_orders:
                log_error(
                    f"Duplicate patch_ordering={task.patch_ordering} found "
                    f"for repository '{repo_rel}'."
                )
                return None
            seen_orders.add(task.patch_ordering)

        repo_tasks.sort(key=lambda item: item.patch_ordering)
        ordered_tasks.extend(repo_tasks)

    return ordered_tasks


def build_patch_tasks(
    manifest: List[Any],
    config_file: Path,
    aaos_dir: Path,
    allowed_tags: Set[str],
) -> Optional[List[PatchTask]]:
    """Validates all JSON entries, filters by tag, and orders tasks per repo."""
    tasks_by_repo: Dict[str, List[PatchTask]] = {}

    for idx, entry in enumerate(manifest):
        patch_file = validate_json_entry(entry, idx + 1, config_file.parent)
        if patch_file is None:
            return None

        tag = entry["tag"].strip()
        if tag not in allowed_tags:
            continue

        repo_rel = entry["repo_path"].strip()
        repo_dir = (aaos_dir / repo_rel).resolve()
        if not repo_dir.is_dir():
            log_error(
                f"Target repository directory '{repo_dir}' does not exist under '{aaos_dir}'."
            )
            return None

        task = PatchTask(
            patch_file=patch_file,
            repo_dir=repo_dir,
            repo_rel=repo_rel,
            description=entry["description"].strip(),
            tag=tag,
            patch_ordering=entry["patch_ordering"],
        )
        tasks_by_repo.setdefault(repo_rel, []).append(task)

    return _order_tasks_by_repo(tasks_by_repo)


def process_patch_task(task: PatchTask) -> bool:
    """Applies and commits a single patch task. Returns True on success."""
    log_info(
        f"Processing repository: {task.repo_rel} "
        f"(tag='{task.tag}', order={task.patch_ordering})"
    )

    if is_git_patch_applied(task.repo_dir, task.patch_file, task.description):
        log_info(
            f"Patch '{task.patch_file.name}' is already applied to "
            f"'{task.repo_rel}'. Skipping."
        )
        return True

    log_info(
        f"Applying and committing patch '{task.patch_file.name}' "
        f"to '{task.repo_rel}'..."
    )
    try:
        apply_and_commit_git_patch(task.repo_dir, task.patch_file, task.description)
    except RuntimeError as err:
        log_error(str(err))
        return False

    log_info(
        f"Successfully applied and committed '{task.patch_file.name}' "
        f"to '{task.repo_rel}'."
    )
    return True


def main() -> int:
    """Main entry point for patch_aaos."""
    args = parse_args()
    aaos_dir_str = args.aaos_dir_flag or args.aaos_dir_pos
    allowed_tags = parse_tag_filter(args.patch_tag_filter)
    if not aaos_dir_str or not allowed_tags:
        log_error(
            "Both --aaos-dir and at least one non-empty tag in "
            "--patch-tag-filter must be specified."
        )
        return 1

    aaos_dir = Path(os.path.expanduser(aaos_dir_str)).resolve()
    if not aaos_dir.is_dir():
        log_error(
            f"AAOS root directory '{aaos_dir}' does not exist or is not a directory."
        )
        return 1

    script_dir = Path(__file__).parent.resolve()
    config_path_str = args.config or str(script_dir / "patches.json")
    config_file = Path(os.path.expanduser(config_path_str)).resolve()

    manifest = load_manifest(config_file)
    tasks = (
        build_patch_tasks(manifest, config_file, aaos_dir, allowed_tags)
        if manifest is not None
        else None
    )
    if tasks is None:
        return 1

    log_info(
        f"Validated {len(manifest)} manifest entries. "
        f"Selected {len(tasks)} patch(es) matching tag filter "
        f"'{args.patch_tag_filter}'."
    )
    if not all(process_patch_task(task) for task in tasks):
        return 1

    log_info("All selected patches applied and committed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
