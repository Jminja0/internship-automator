"""Fill in application forms from a saved profile.

Currently supports Greenhouse-hosted applications (boards.greenhouse.io),
since that's the most standardized ATS among the listings this tool
tracks. Other ATS platforms (Workday, Lever, etc.) use different form
structures and aren't handled yet.

This module only ever fills fields -- it never clicks submit. Review
every application yourself before sending it.
"""

import json
from pathlib import Path

from .browser import goto, open_browser


def load_profile(path="profile.json"):
    """Load applicant info from a JSON file (see profile.example.json)."""
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Profile not found: {path}. "
            "Copy profile.example.json to profile.json and fill it in."
        ) from None


def detect_ats(url):
    """Identify which application system a listing URL points to."""
    if "greenhouse.io" in url:
        return "greenhouse"
    return "unknown"


# How long to wait for an optional field before deciding it isn't on the page.
# Playwright's default is 30 s *per field*, which made a form missing a few
# fields stall for minutes.
FIELD_TIMEOUT_MS = 1500

# Each entry lists the classic Greenhouse selector first, then the ids used by
# the newer job-boards.greenhouse.io form (comma = "either one").
GREENHOUSE_FIELDS = {
    "first_name": "input[name='job_application[first_name]'], input#first_name",
    "last_name": "input[name='job_application[last_name]'], input#last_name",
    "email": "input[name='job_application[email]'], input#email",
    "phone": "input[name='job_application[phone]'], input#phone",
}
GREENHOUSE_RESUME = "input[name='job_application[resume]'], input#resume"


def fill_greenhouse_form(page, profile):
    """Fill the common fields on a Greenhouse application form.

    Some postings add custom questions on top of these, which this function
    leaves untouched for you to fill. Returns the names of fields it filled.
    """

    filled = []

    for key, selector in GREENHOUSE_FIELDS.items():
        value = profile.get(key, "")
        if not value:
            continue
        try:
            page.fill(selector, value, timeout=FIELD_TIMEOUT_MS)
            filled.append(key)
        except Exception:
            # Field not present on this particular posting -- skip it
            # rather than failing the whole run.
            continue

    resume_path = profile.get("resume_path")
    if resume_path:
        if not Path(resume_path).is_file():
            print(f"Warning: resume not found at {resume_path!r}; skipping upload.")
        else:
            try:
                page.set_input_files(
                    GREENHOUSE_RESUME, resume_path, timeout=FIELD_TIMEOUT_MS
                )
                filled.append("resume")
            except Exception:
                pass

    return filled


def apply_to_listing(url, profile, headless=False):
    """Open a listing and fill what it can, then hand control back to you.

    Returns "filled" if a supported ATS was detected and fields were
    filled, or "unsupported" if the ATS isn't handled yet -- either
    way, nothing is ever submitted automatically.
    """

    ats = detect_ats(url)

    with open_browser(headless=headless) as page:
        goto(page, url)

        if ats == "greenhouse":
            print("Page loaded. If this is a job description page, click")
            print("'Apply' yourself to reach the actual form.")
            input("Once you're on the page with the fillable fields, press Enter to fill it...")

            filled = fill_greenhouse_form(page, profile)
            print(f"Filled: {', '.join(filled) or 'nothing (no known fields found)'}.")
            print("Review every field, then submit manually.")
            input("Press Enter here once you're done with this listing...")
            return "filled"

        print(f"No autofill support yet for this ATS ({url}).")
        print("Fill it out manually, or add a handler for this platform.")
        input("Press Enter here once you're done with this listing...")
        return "unsupported"
