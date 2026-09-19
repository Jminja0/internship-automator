import requests


LISTINGS_URL = (
    "https://raw.githubusercontent.com/"
    "SimplifyJobs/Summer2027-Internships/dev/"
    ".github/scripts/listings.json"
)


def fetch_internships():
    """Download the latest internship listings from SimplifyJobs."""

    response = requests.get(LISTINGS_URL, timeout=10)

    # Raise an exception if GitHub returned an error.
    response.raise_for_status()

    return response.json()
