"""Fill in application forms from a saved profile.

Currently supports Greenhouse-hosted applications (boards.greenhouse.io),
since that's the most standardized ATS among the listings this tool
tracks. Other ATS platforms (Workday, Lever, etc.) use different form
structures and aren't handled yet.

This module only ever fills fields -- it never clicks submit. Review
every application yourself before sending it.
"""

import json

from .browser import goto, open_browser


def load_profile(path="profile.json"):
    """Load applicant info from a JSON file (see profile.example.json)."""
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def detect_ats(url):
    """Identify which application system a listing URL points to."""
    if "greenhouse.io" in url:
        return "greenhouse"
    return "unknown"


def fill_greenhouse_form(page, profile):
    """Fill the common fields on a Greenhouse application form."""

    # Greenhouse's embedded application form uses these field names
    # on most job boards. Some postings add custom questions on top
    # of these, which this function leaves untouched for you to fill.
    field_map = {
        "input[name='job_application[first_name]']": profile.get("first_name", ""),
        "input[name='job_application[last_name]']": profile.get("last_name", ""),
        "input[name='job_application[email]']": profile.get("email", ""),
        "input[name='job_application[phone]']": profile.get("phone", ""),
    }

    for selector, value in field_map.items():
        if not value:
            continue
        try:
            page.fill(selector, value)
        except Exception:
            # Field not present on this particular posting -- skip it
            # rather than failing the whole run.
            continue

    resume_path = profile.get("resume_path")
    if resume_path:
        try:
            page.set_input_files(
                "input[name='job_application[resume]']", resume_path
            )
        except Exception:
            pass


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

            fill_greenhouse_form(page, profile)
            print("Form filled. Review every field, then submit manually.")
            input("Press Enter here once you're done with this listing...")
            return "filled"

        print(f"No autofill support yet for this ATS ({url}).")
        print("Fill it out manually, or add a handler for this platform.")
        input("Press Enter here once you're done with this listing...")
        return "unsupported"
