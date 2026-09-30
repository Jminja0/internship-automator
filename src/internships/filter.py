import datetime
import re

# Word-boundary matching matters here: a bare `"intern" in text` also matches
# "internal", "international", and "internet", which lets full-time roles through.
INTERN_RE = re.compile(r"\b(?:interns?|internships?|co-?ops?)\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(20\d{2})\b")
OLD_SEASON_RE = re.compile(
    r"\b(?:summer|fall|autumn|winter|spring)\s+(20\d{2})\b", re.IGNORECASE
)

SOFTWARE_CATEGORIES = {"software", "software engineering"}
SOFTWARE_TITLE_RE = re.compile(
    r"\b(?:software|developer|full[\s-]?stack|back[\s-]?end|front[\s-]?end"
    r"|information technology|it intern|technical support|computer technician"
    r"|systems intern)\b",
    re.IGNORECASE,
)

TARGET_CITIES = (
    "seattle", "bellevue", "redmond", "kirkland", "bothell", "lynnwood",
    "everett", "renton", "kent", "tukwila", "tacoma",
)
CITY_RE = re.compile(r"\b(" + "|".join(TARGET_CITIES) + r")\b")
# "Everett, MA", "Kent, UK", and "Bellevue, NE" are not Seattle-area jobs.
STATE_RE = re.compile(r",\s*([a-z]{2})\b(?!\w)")
# "us" is a country code ("Seattle, US"), not another state.
WASHINGTON_TOKENS = {"wa", "us"}
WASHINGTON_STATE_RE = re.compile(
    r"(?:\bwashington(?:\s+state)?\b|(?:^|,\s*)wa\b)", re.IGNORECASE
)
WASHINGTON_DC_RE = re.compile(
    r"\bwashington\s*,?\s*(?:d\.?c\.?|district of columbia)\b",
    re.IGNORECASE,
)


def is_active(internship):
    """Return True if the internship is currently active and visible."""
    return internship.get("active", False) and internship.get("is_visible", True)


def _title_and_terms(internship):
    return " ".join([internship.get("title", ""), *internship.get("terms", [])])


def is_summer_2027(internship):
    """Keep the curated list on Summer 2027; accept current ATS internships.

    Official feeds have no season field, so an ATS posting qualifies when its
    title says intern/co-op and nothing marks it as an earlier year.
    """
    header = _title_and_terms(internship)
    if internship.get("source") == "simplify":
        return "summer 2027" in header.lower()

    if not INTERN_RE.search(header):
        return False

    # A year in the title/terms that isn't 2027 (e.g. "Summer 2026") is old.
    header_years = set(YEAR_RE.findall(header))
    if header_years and "2027" not in header_years:
        return False

    # In the description only trust explicit season+year phrases, since bare
    # years show up in unrelated text (copyright lines, company history, ...).
    description = internship.get("description", "")
    season_years = {year for year in OLD_SEASON_RE.findall(description)}
    if season_years and "2027" not in season_years and "2027" not in header_years:
        return False
    return True


def is_software_related(internship):
    """Return True if the internship is software-related."""
    category = internship.get("category", "").lower()
    if category in SOFTWARE_CATEGORIES:
        return True
    return bool(SOFTWARE_TITLE_RE.search(internship.get("title", "")))


def _is_target_location(location):
    location_lower = location.lower()
    if "remote" in location_lower:
        return True
    # Accept anywhere in Washington state, including locations such as
    # "Spokane, WA" and "Washington, United States", but not Washington, DC.
    if (WASHINGTON_STATE_RE.search(location_lower)
            and not WASHINGTON_DC_RE.search(location_lower)):
        return True
    if not CITY_RE.search(location_lower):
        return False
    state = STATE_RE.search(location_lower)
    return state is None or state.group(1) in WASHINGTON_TOKENS


def is_target_location(internship):
    """Return True for Washington-state or remote positions."""
    return any(_is_target_location(loc) for loc in internship.get("locations", []))


def parse_posted_at(value):
    """Parse ISO dates and Unix seconds/milliseconds into an aware datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.datetime.fromtimestamp(seconds, tz=datetime.timezone.utc)
    text = str(value).strip()
    if text.isdigit():
        return parse_posted_at(int(text))
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def is_recent(internship, max_age_days=30, now=None, first_seen=None):
    """Reject known-old jobs.

    When a provider exposes no post date (Lever), fall back to when this
    scanner first saw the job (`first_seen`, from SQLite). A job with no date
    that has never been seen is allowed through on first discovery.
    """
    posted_at = parse_posted_at(
        internship.get("posted_at", internship.get("date_posted"))
    )
    if posted_at is None:
        posted_at = parse_posted_at(first_seen)
    if posted_at is None:
        return True
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return posted_at >= now - datetime.timedelta(days=max_age_days)


def filter_internships(internships, max_age_days=30, first_seen_by_id=None):
    """Apply all of our internship filters.

    Cheap string checks run before the date checks; `first_seen_by_id` maps
    job id -> first_seen timestamp for jobs the scanner has already stored.
    """
    first_seen_by_id = first_seen_by_id or {}
    return [
        internship
        for internship in internships
        if is_active(internship)
        and is_summer_2027(internship)
        and is_software_related(internship)
        and is_target_location(internship)
        and is_recent(
            internship,
            max_age_days=max_age_days,
            first_seen=first_seen_by_id.get(internship.get("id")),
        )
    ]


FUNNEL_STAGES = ("fetched", "active", "intern", "software", "location", "recent")


def source_label(internship):
    """Group key for reporting: one bucket for Simplify, one per company otherwise."""
    if internship.get("source") == "simplify":
        return "SimplifyJobs"
    return internship.get("company_name") or internship.get("source", "unknown")


def filter_funnel(internships, max_age_days=30, first_seen_by_id=None):
    """Count, per source, how many postings survive each filter in turn.

    Stages are cumulative and applied in the same order as
    `filter_internships`, so the last column equals that function's result.
    Shows *why* a source contributes nothing (e.g. 300 fetched, 0 intern).
    """
    first_seen_by_id = first_seen_by_id or {}
    checks = (
        ("active", is_active),
        ("intern", is_summer_2027),
        ("software", is_software_related),
        ("location", is_target_location),
    )
    funnel = {}
    for internship in internships:
        counts = funnel.setdefault(
            source_label(internship), dict.fromkeys(FUNNEL_STAGES, 0))
        counts["fetched"] += 1
        for name, check in checks:
            if not check(internship):
                break
            counts[name] += 1
        else:
            if is_recent(
                internship,
                max_age_days=max_age_days,
                first_seen=first_seen_by_id.get(internship.get("id")),
            ):
                counts["recent"] += 1
    return funnel
