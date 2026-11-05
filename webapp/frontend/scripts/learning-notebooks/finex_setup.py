# FinEx Learning · lab setup. Run this cell first; it only defines helpers.
# Data: Kenneth R. French Data Library (Tuck School of Business, Dartmouth),
# Asia Pacific ex Japan series (Australia, Hong Kong, New Zealand, Singapore),
# downloaded on first use and cached next to the notebook.
import hashlib
import io
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

FRENCH = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
CACHE = Path("finex_data")
CACHE.mkdir(exist_ok=True)


def _lines(name):
    path = CACHE / f"{name}.csv"
    if not path.exists():
        with urllib.request.urlopen(f"{FRENCH}{name}_CSV.zip", timeout=60) as response:
            archive = zipfile.ZipFile(io.BytesIO(response.read()))
            path.write_bytes(archive.read(archive.namelist()[0]))
    return path.read_text(encoding="latin-1").splitlines()


def load_french(name, table=None, percent=True):
    """One monthly table from a French data library file, indexed by month.

    `table` is the title above the table (e.g. "Average Value Weighted Returns -- Monthly");
    None means the first monthly table. Returns are converted to decimals.
    """
    tables, title, current = {}, "", None
    for line in _lines(name):
        cells = [c.strip() for c in line.split(",")]
        if line.lstrip().startswith(","):
            current = []
            tables.setdefault(title or "first", (cells[1:], current))
            continue
        if current is not None and len(cells[0]) == 6 and cells[0].isdigit():
            current.append(cells)
            continue
        if line.strip():
            title, current = line.strip(), None
    key = table or next(k for k, (_, rows) in tables.items() if rows)
    header, rows = tables[key]
    frame = pd.DataFrame(
        [r[1:] for r in rows],
        columns=header,
        index=pd.PeriodIndex([r[0] for r in rows], freq="M"),
    ).astype(float).replace(-99.99, np.nan)
    return frame / 100 if percent else frame


def check(name, condition, hint):
    """Automatic check: passes quietly, or explains what to look at."""
    if not bool(condition):
        raise AssertionError(f"✗ {name}. Hint: {hint}")
    print(f"✓ {name}")


def completion_code(lab):
    code = hashlib.sha256(f"finex-quant-{lab}".encode()).hexdigest()[:6].upper()
    print(f"\nAll checks passed. Your completion code for the course page: FINEX-{lab.upper()}-{code}")


def annualise(returns):
    """Mean, volatility, Sharpe and t-stat of monthly excess returns, annualised."""
    r = returns.dropna()
    mean, vol = r.mean() * 12, r.std() * np.sqrt(12)
    return pd.Series({"mean": mean, "vol": vol, "sharpe": mean / vol,
                      "t_stat": r.mean() / r.std() * np.sqrt(len(r)), "months": len(r)})


print("Setup complete. Data source: Kenneth R. French Data Library · Asia Pacific ex Japan.")
