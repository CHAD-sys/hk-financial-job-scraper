"""
Adapter registry.

Maps the `ats` string from companies.yaml to the adapter class that
handles that source. Later phases register entries here as new adapters
are implemented:

    from hk_jobs.adapters.workday import WorkdayAdapter
    ADAPTERS["workday"] = WorkdayAdapter
"""

from hk_jobs.adapters.base import BaseAdapter

# Keyed by the string used in the `ats:` field of companies.yaml.
ADAPTERS: dict[str, type[BaseAdapter]] = {}
