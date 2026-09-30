import hashlib
import re
from html import unescape


def text_from_html(value):
    """Strip tags. Greenhouse sends entity-escaped HTML ("&lt;p&gt;..."), so
    unescape first, strip tags, then unescape the remaining text entities."""
    value = re.sub(r"<[^>]+>", " ", unescape(value or ""))
    return " ".join(unescape(value).split())


def locations_from_text(value):
    if not value:
        return []
    return [part.strip() for part in re.split(r"\s*[;|]\s*", value) if part.strip()]


def stable_id(source, board, source_job_id):
    raw = f"{source}:{board}:{source_job_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def infer_terms(title, description):
    text = f"{title} {description}".lower()
    if "2027" in text and ("summer" in text or "intern" in text):
        return ["Summer 2027"]
    return []


def normalized_job(*, source, board, source_job_id, company, title, locations,
                   url, posted_at=None, updated_at=None, description="",
                   workplace_type=None, active=True):
    clean_description = text_from_html(description)
    return {
        "id": stable_id(source, board, source_job_id),
        "source": source,
        "source_job_id": str(source_job_id),
        "company_name": company,
        "title": title,
        "locations": locations or ([workplace_type] if workplace_type else []),
        "url": url,
        "date_posted": posted_at,
        "posted_at": posted_at,
        "source_updated_at": updated_at,
        "description": clean_description,
        "terms": infer_terms(title, clean_description),
        "active": active,
    }
