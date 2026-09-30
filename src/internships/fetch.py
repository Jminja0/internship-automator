"""Fetch and normalize internship postings from supported job boards."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from src.internships.providers import ashby, greenhouse, lever, simplify

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCES_PATH = PROJECT_ROOT / "sources.json"
MAX_WORKERS = 8

PROVIDERS = {
    "ashby": ashby.fetch,
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "simplify": simplify.fetch,
}


def canonical_url(url):
    """Remove common tracking parameters so the same job deduplicates."""
    parts = urlsplit((url or "").strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"gh_src", "lever-source", "source"}
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), "")
    )


def _fallback_key(job):
    fields = [job.get("company_name", ""), job.get("title", "")]
    fields.extend(job.get("locations", []))
    normalized = "|".join(" ".join(value.lower().split()) for value in fields)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def deduplicate(internships):
    """Deduplicate by canonical application URL, then job identity fields.

    Call this *after* filtering: otherwise a closed or non-matching copy of a
    job (e.g. an inactive Simplify row) can shadow an active copy from an
    official feed and the job disappears from the results.
    """
    seen_urls = set()
    seen_jobs = set()
    unique = []
    for internship in internships:
        url_key = canonical_url(internship.get("url"))
        job_key = _fallback_key(internship)
        if (url_key and url_key in seen_urls) or job_key in seen_jobs:
            continue
        if url_key:
            seen_urls.add(url_key)
            internship["url"] = url_key
        seen_jobs.add(job_key)
        unique.append(internship)
    return unique


def load_sources(path=None):
    """Load source configuration.

    With no path, use the project's sources.json and fall back to Simplify
    only if it is missing. An explicitly given path that doesn't exist is an
    error rather than a silent fallback, so a typo can't quietly shrink the
    scan to a single source.
    """
    if path is None:
        source_path = DEFAULT_SOURCES_PATH
        if not source_path.exists():
            print(f"Warning: {source_path} not found -- scanning SimplifyJobs only.")
            print("  Copy sources.example.json to sources.json to add company boards.")
            return [{"provider": "simplify", "name": "SimplifyJobs"}]
    else:
        source_path = Path(path)
        if not source_path.exists():
            raise FileNotFoundError(f"Sources file not found: {source_path}")
    with source_path.open(encoding="utf-8") as source_file:
        config = json.load(source_file)
    return config.get("sources", config)


def make_session():
    """Build a session that retries transient failures (429/5xx) with backoff."""
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = "internship-automator/1.0"
    return session


def _fetch_source(source):
    """Fetch one source. Returns (label, jobs, error); never raises."""
    provider = source.get("provider", "").lower()
    label = source.get("name", provider)
    fetcher = PROVIDERS.get(provider)
    if not fetcher:
        return label, [], f"unknown provider {provider!r}"
    try:
        # One session per source: requests.Session isn't documented as thread-safe.
        with make_session() as session:
            return label, fetcher(source, session=session), None
    except Exception as error:  # a bad board must never abort the whole scan
        return label, [], error


def fetch_internships(sources_path=None):
    """Fetch all configured sources concurrently, continuing if one fails.

    Returns the raw postings, in source order, without filtering or
    deduplication -- see `filter_internships` and `deduplicate`.
    """
    sources = [s for s in load_sources(sources_path) if s.get("enabled", True)]
    boards = sum(1 for s in sources if s.get("provider", "").lower() != "simplify")
    print(f"Scanning {len(sources)} source(s): Simplify + {boards} company board(s).")
    internships = []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(sources) or 1)) as pool:
        for label, jobs, error in pool.map(_fetch_source, sources):
            if error:
                print(f"  Warning: could not fetch {label}: {error}")
                continue
            internships.extend(jobs)
            print(f"  {label}: {len(jobs)} posting(s)")
    return internships
