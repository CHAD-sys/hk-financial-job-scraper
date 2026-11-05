"""Build and verify the quant course lab notebooks.

    python scripts/learning-notebooks/build.py [--no-execute]

Writes learner notebooks to public/learning-assets/notebooks/quant/ (served by
the site) and solution notebooks to course-materials/quant/solutions/ (never
served). Unless --no-execute, every solution notebook is executed against the
live French Data Library files, so a check that no longer passes on current
data fails the build instead of failing a learner.

Needs: nbformat, nbclient, ipykernel, pandas, numpy, scipy, statsmodels,
scikit-learn, cvxpy.
"""
import shutil
import sys
import tempfile
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

from labs import LAB4_REFERENCE, LABS

HERE = Path(__file__).parent
FRONTEND = HERE.parents[1]
PUBLIC = FRONTEND / "public" / "learning-assets" / "notebooks" / "quant"
SOLUTIONS = FRONTEND / "course-materials" / "quant" / "solutions"
SETUP = (HERE / "finex_setup.py").read_text()


def notebook(name, cells, solution):
    out = []
    for cell in cells:
        kind = cell[0]
        if kind == "md":
            out.append(new_markdown_cell(cell[1]))
        elif kind == "setup":
            extra = LAB4_REFERENCE if name.startswith("lab4") else ""
            out.append(new_code_cell(SETUP + extra))
        elif kind == "code":
            out.append(new_code_cell(cell[1]))
        elif kind == "ex":
            out.append(new_code_cell(cell[2] if solution else cell[1], metadata={"tags": ["exercise"]}))
    nb = new_notebook(cells=out)
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    nb.metadata["finex"] = {"course": "quant", "lab": name, "solution": solution}
    return nb


def main(execute=True):
    PUBLIC.mkdir(parents=True, exist_ok=True)
    SOLUTIONS.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="finex-labs-"))
    failures = []
    for name, cells in LABS.items():
        nbformat.write(notebook(name, cells, solution=False), PUBLIC / f"{name}.ipynb")
        solved = notebook(name, cells, solution=True)
        if execute and not name.startswith("capstone"):
            try:
                NotebookClient(solved, timeout=900, kernel_name="python3",
                               resources={"metadata": {"path": str(workdir)}}).execute()
                outputs = "".join(o.get("text", "") for c in solved.cells for o in c.get("outputs", []))
                assert "completion code" in outputs, "no completion code printed"
                print(f"✓ {name}: all checks pass")
            except Exception as exc:  # report every failing lab, not just the first
                failures.append(name)
                print(f"✗ {name}: {str(exc).splitlines()[-1] if str(exc) else exc!r}")
        nbformat.write(solved, SOLUTIONS / f"{name}-solution.ipynb")
    shutil.rmtree(workdir, ignore_errors=True)
    if failures:
        sys.exit(f"Failing labs: {', '.join(failures)}")


if __name__ == "__main__":
    main(execute="--no-execute" not in sys.argv)
