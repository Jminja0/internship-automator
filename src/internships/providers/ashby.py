from .common import locations_from_text, normalized_job


def fetch(source, session):
    board = source["board"]
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
    response = session.get(url, params={"includeCompensation": "true"}, timeout=20)
    response.raise_for_status()
    company = source.get("name", board)
    jobs = []
    for item in response.json().get("jobs", []):
        if item.get("isListed") is False:
            continue
        locations = locations_from_text(item.get("location") or "")
        workplace = item.get("workplaceType")
        if workplace and workplace.lower() == "remote" and not any(
            "remote" in value.lower() for value in locations
        ):
            locations.append("Remote")
        jobs.append(normalized_job(
            source="ashby", board=board,
            source_job_id=item.get("id") or item.get("jobUrl") or "",
            company=company, title=item.get("title") or "", locations=locations,
            url=item.get("applyUrl") or item.get("jobUrl") or "",
            posted_at=item.get("publishedAt"), updated_at=item.get("publishedAt"),
            description=item.get("descriptionHtml") or item.get("descriptionPlain") or "",
            workplace_type=workplace,
        ))
    return jobs
