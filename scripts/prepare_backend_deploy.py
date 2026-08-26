#!/usr/bin/env python3
"""Assemble the backend-only Railway upload from the canonical project sources.

Railway uploads ``webapp/backend`` as the whole application.  The salary engine
and its anchor JSON live at the repository root, so copying only ``hk_jobs``
creates a package whose loader can never find its data.  This command stages the
Python package, the two runtime salary files, and (normally) the built frontend
as one reproducible deployment directory.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SALARY_FILES = (
    "hk_salary_anchors.json",
    "hk_salary_anchor_provenance.json",
    "employer_compensation_segments.json",
    "disclosed_salary_evidence.json",
)


def _remove_generated_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _replace_tree(source: Path, destination: Path, *, ignore: shutil.IgnorePattern) -> None:
    """Replace one generated deployment tree only after its new copy is complete."""
    if not source.is_dir():
        raise FileNotFoundError(f"Deployment source directory is missing: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{destination.name}-stage-", dir=destination.parent
    ) as temporary:
        staged = Path(temporary) / destination.name
        shutil.copytree(source, staged, ignore=ignore)
        _remove_generated_path(destination)
        staged.replace(destination)


def _stage_salary_data(project_root: Path, backend_dir: Path) -> None:
    source = project_root / "salary_guidlines"
    for filename in RUNTIME_SALARY_FILES:
        if not (source / filename).is_file():
            raise FileNotFoundError(f"Runtime salary file is missing: {source / filename}")

    with tempfile.TemporaryDirectory(prefix="salary-runtime-") as temporary:
        staged_source = Path(temporary) / "salary_guidlines"
        staged_source.mkdir()
        for filename in RUNTIME_SALARY_FILES:
            shutil.copy2(source / filename, staged_source / filename)
        _replace_tree(staged_source, backend_dir / "salary_guidlines", ignore=lambda *_: set())


def _validate_staged_salary_runtime(project_root: Path, backend_dir: Path) -> None:
    source_anchor = project_root / "salary_guidlines" / RUNTIME_SALARY_FILES[0]
    staged_anchor = backend_dir / "salary_guidlines" / RUNTIME_SALARY_FILES[0]
    source_data = json.loads(source_anchor.read_text(encoding="utf-8"))
    staged_data = json.loads(staged_anchor.read_text(encoding="utf-8"))
    if staged_data != source_data or not staged_data.get("tables_monthly_hkd"):
        raise RuntimeError("Staged salary anchors do not match the canonical table")

    source_clamp = project_root / "hk_jobs" / "salary_clamp.py"
    staged_clamp = backend_dir / "hk_jobs" / "salary_clamp.py"
    if staged_clamp.read_bytes() != source_clamp.read_bytes():
        raise RuntimeError("Staged salary clamp does not match the canonical implementation")


def prepare_backend_deploy(
    *,
    project_root: Path = PROJECT_ROOT,
    backend_dir: Path | None = None,
    include_frontend: bool = True,
) -> Path:
    """Stage and validate the complete backend-only Railway upload."""
    project_root = project_root.resolve()
    backend_dir = (backend_dir or project_root / "webapp" / "backend").resolve()
    backend_dir.mkdir(parents=True, exist_ok=True)

    package_ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "graphify-out")
    _replace_tree(project_root / "hk_jobs", backend_dir / "hk_jobs", ignore=package_ignore)
    _stage_salary_data(project_root, backend_dir)

    if include_frontend:
        _replace_tree(
            project_root / "webapp" / "frontend" / "dist",
            backend_dir / "frontend_dist",
            ignore=shutil.ignore_patterns(".DS_Store"),
        )

    _validate_staged_salary_runtime(project_root, backend_dir)
    return backend_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="Stage only the shared Python and salary runtime (used by focused tests).",
    )
    args = parser.parse_args()
    backend = prepare_backend_deploy(include_frontend=not args.skip_frontend)
    print(f"Prepared backend deployment at {backend}")


if __name__ == "__main__":
    main()
