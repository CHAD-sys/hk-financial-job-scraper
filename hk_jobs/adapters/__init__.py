"""
Adapter registry.

Maps the `ats` string from companies.yaml to the adapter class that
handles that source. Add new adapters here as they are implemented.
"""

from hk_jobs.adapters.base import BaseAdapter
from hk_jobs.adapters.workday import WorkdayAdapter

# Keyed by the string used in the `ats:` field of companies.yaml.
ADAPTERS: dict[str, type[BaseAdapter]] = {
    "workday": WorkdayAdapter,
}
