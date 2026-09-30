from .common import stable_id

LISTINGS_URL = (
    "https://raw.githubusercontent.com/"
    "SimplifyJobs/Summer2027-Internships/dev/"
    ".github/scripts/listings.json"
)


def fetch(source, session):
    response = session.get(source.get("url", LISTINGS_URL), timeout=20)
    response.raise_for_status()
    jobs = response.json()
    for job in jobs:
        job.setdefault("source", "simplify")
        job.setdefault("source_job_id", str(job.get("id", job.get("url", ""))))
        job.setdefault("posted_at", job.get("date_posted"))
        job.setdefault("source_updated_at", None)
        if not job.get("id"):
            job["id"] = stable_id("simplify", "summer2027", job["source_job_id"])
    return jobs
