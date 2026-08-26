"""The backend-only Railway upload contains the shared salary runtime."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from hk_jobs import salary_anchors
from scripts.prepare_backend_deploy import prepare_backend_deploy

ROOT = Path(__file__).resolve().parents[1]


def test_prepared_backend_imports_the_current_salary_anchors(tmp_path: Path) -> None:
    """A backend-only upload must price from the same anchors as the pipeline."""
    backend = tmp_path / "backend"
    backend.mkdir()

    prepare_backend_deploy(
        project_root=ROOT,
        backend_dir=backend,
        include_frontend=False,
    )

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from hk_jobs import salary_anchors; "
                "print(json.dumps({"
                "'module': salary_anchors.__file__, "
                "'tables': len(salary_anchors.TABLES), "
                "'fingerprint': salary_anchors.fingerprint()"
                "}))"
            ),
        ],
        cwd=backend,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    loaded = json.loads(result.stdout)
    assert Path(loaded["module"]).is_relative_to(backend)
    assert loaded["tables"] == len(salary_anchors.TABLES) == 7
    assert loaded["fingerprint"] == salary_anchors.fingerprint()
    assert (
        backend / "hk_jobs" / "salary_clamp.py"
    ).read_bytes() == (ROOT / "hk_jobs" / "salary_clamp.py").read_bytes()
    assert (backend / "salary_guidlines" / "hk_salary_anchors.json").is_file()
    assert (backend / "salary_guidlines" / "hk_salary_anchor_provenance.json").is_file()
