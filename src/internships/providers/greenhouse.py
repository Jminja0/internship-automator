from .common import locations_from_text, normalized_job


def fetch(source, session):
    board = source["board"]
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
    response = session.get(url, timeout=20)
    response.raise_for_status()
    company = source.get("name", board)
    jobs = []
    for item in response.json().get("jobs", []):
        jobs.append(normalized_job(
            source="greenhouse", board=board, source_job_id=item["id"],
            company=company, title=item.get("title") or "",
            locations=locations_from_text((item.get("location") or {}).get("name") or ""),
            url=item.get("absolute_url") or "", posted_at=item.get("first_published"),
            updated_at=item.get("updated_at"), description=item.get("content") or "",
        ))
    return jobs
