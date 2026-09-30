from .common import locations_from_text, normalized_job


def fetch(source, session):
    board = source["board"]
    url = f"https://api.lever.co/v0/postings/{board}"
    response = session.get(url, params={"mode": "json"}, timeout=20)
    response.raise_for_status()
    company = source.get("name", board)
    jobs = []
    for item in response.json():
        categories = item.get("categories") or {}
        jobs.append(normalized_job(
            source="lever", board=board, source_job_id=item["id"],
            company=company, title=item.get("text") or "",
            locations=locations_from_text(categories.get("location") or ""),
            url=item.get("applyUrl") or item.get("hostedUrl") or "",
            description=item.get("descriptionPlain") or "",
            workplace_type=categories.get("workplaceType"),
        ))
    return jobs
