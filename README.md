# Internship Automator

Find, filter, track, and open internship applications. The fetcher combines the
SimplifyJobs list with official public Greenhouse, Ashby, and Lever job-board
APIs, deduplicates results, and excludes known postings older than 30 days. The
Simplify feed stays limited to Summer 2027; official company feeds accept
current internship/co-op roles unless they are explicitly labeled 2026-only.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # only needed for the `apply` command
cp profile.example.json profile.json
python3 main.py
```

Scanning (`python3 main.py`) only needs `requests`; Playwright and the Google
libraries are loaded on demand by `apply` and `resync`. Paths resolve relative
to the project, so the commands work from any directory.

Matches are saved to SQLite and exported to `data/matching_internships.csv`.

| Command | What it does |
| --- | --- |
| `python3 main.py` | Fetch, filter, deduplicate, store, and export matches |
| `python3 main.py list [--status new]` | Show tracked applications |
| `python3 main.py apply` | Open new applications one at a time and autofill (Greenhouse) |
| `python3 main.py resync` | Push every processed application's status to your Google Sheet |

## How matching works

A posting is kept only if it is active, software-related, in the Seattle area
(or anywhere else in Washington state, or remote), recent, and an internship
for the right term.

- **Internship detection** uses whole-word matches on the job *title*
  (`intern`, `internship`, `co-op`), so descriptions mentioning "internal
  teams" no longer turn full-time roles into matches.
- **Location** matches Seattle-area cities, and when a state is given it must
  be Washington, so "Everett, MA" and "Kent, UK" are excluded. Any location
  containing "remote" is accepted.
- **Filtering runs before deduplication**, so a closed or non-matching copy of
  a job can't hide an active copy from another source.
- Sources are fetched concurrently with automatic retries on 429/5xx.

## Job-board sources

Edit `sources.json` to add companies. Board identifiers come from the public
careers URL:

- Greenhouse: `boards.greenhouse.io/BOARD` or `job-boards.greenhouse.io/BOARD`
- Ashby: `jobs.ashbyhq.com/BOARD`
- Lever: `jobs.lever.co/BOARD`

No API key is required for these read-only job-board endpoints. A source failure
prints a warning and does not stop the remaining boards.

```json
{"provider": "greenhouse", "name": "Company", "board": "company"}
```

Use another configuration file or age limit when needed:

```bash
python3 main.py --sources my-sources.json --max-age-days 14
```

A `--sources` path that doesn't exist is an error (it does not silently fall
back to Simplify only).

Greenhouse and Ashby expose publication timestamps. Lever does not, so an
unknown-date Lever role is allowed through on first discovery; after that its
age is measured from SQLite's `first_seen`, and it drops out once it is older
than `--max-age-days`.

LinkedIn is intentionally not scraped. LinkedIn does not provide a general
public jobs-search API, and scraping it is brittle and can violate its terms.
Official ATS feeds are faster, more reliable, and link directly to employers.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
