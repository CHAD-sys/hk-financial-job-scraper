"""
Adapter registry.

Maps the `ats` string from companies.yaml to the adapter class that
handles that source. Add new adapters here as they are implemented.
"""

from hk_jobs.adapters.base import BaseAdapter
from hk_jobs.adapters.efc import EfcAdapter
from hk_jobs.adapters.eightfold import EightfoldAdapter
from hk_jobs.adapters.indeed import IndeedAdapter
from hk_jobs.adapters.jobsdb import JobsDBAdapter
from hk_jobs.adapters.linkedin import LinkedInAdapter
from hk_jobs.adapters.longtail import LongtailAdapter
from hk_jobs.adapters.workday import WorkdayAdapter

# Keyed by the string used in the `adapter:` field of companies.yaml.
ADAPTERS: dict[str, type[BaseAdapter]] = {
    "workday": WorkdayAdapter,
    "eightfold": EightfoldAdapter,
    "jobsdb": JobsDBAdapter,
    "indeed": IndeedAdapter,
    "linkedin": LinkedInAdapter,
    "longtail": LongtailAdapter,
    "efinancialcareers": EfcAdapter,
}
