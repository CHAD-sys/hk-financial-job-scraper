# HK Financial Job Scraper

A daily scraper for open job postings at the 30 largest Hong Kong financial institutions (banks, insurers, asset managers). It calls each company's ATS (Applicant Tracking System) API directly — primarily Workday, Eightfold AI, and SAP SuccessFactors — extracts structured features from each posting (title, skills, seniority, location), and persists them to a SQLite database with soft-delete semantics so historical data is never lost. The output is a queryable job database intended for downstream CV-matching workflows; scraping and storage are the only scope of this project.

## Legal notice — JobsDB fallback

For companies whose own ATS (Taleo, iCIMS) is hostile to scraping, this project falls back to scraping `hk.jobsdb.com`. **This violates JobsDB's Terms of Service and must not be used in production** without either (a) written permission from JobsDB / SEEK or (b) a paid data-feed arrangement. The fallback is acceptable for a prototype only. See `hk_jobs/adapters/jobsdb.py` for full details.
