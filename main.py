import argparse
import csv
import sys
from pathlib import Path

from src.database import (
    get_applications,
    get_first_seen_map,
    initialize_database,
    save_internships,
    update_status,
)
from src.internships.fetch import deduplicate, fetch_internships
from src.internships.filter import FUNNEL_STAGES, filter_funnel, filter_internships

PROJECT_ROOT = Path(__file__).resolve().parent
CSV_PATH = PROJECT_ROOT / "data" / "matching_internships.csv"
DEFAULT_PROFILE = str(PROJECT_ROOT / "profile.json")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Find and track internships.")

    parser.add_argument(
        "--filter",
        action="store_true",
        help="Deprecated and ignored: filters are always applied.")
    parser.add_argument(
        "--sources",
        default=None,
        help="Path to source configuration (default: sources.json).")
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=30,
        help="Exclude postings older than this many days (default: 30).")

    subparsers = parser.add_subparsers(
        dest="command")

    list_parser = subparsers.add_parser(
        "list",
        help="List tracked applications from the local database.")
    list_parser.add_argument(
        "--status",
        default=None,
        help="Only show applications with this status (e.g. new, filled).")

    apply_parser = subparsers.add_parser(
        "apply",
        help="Open each new application one at a time and track it.")
    apply_parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        help="Path to your profile JSON (see profile.example.json).")

    resync_parser = subparsers.add_parser(
        "resync",
        help="Re-push every processed application's status to the Google Sheet.")
    resync_parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        help="Path to your profile JSON (see profile.example.json).")

    return parser.parse_args()


def open_worksheet(profile):
    """Open the configured Google Sheet tab, or return None if not configured."""
    if not (profile.get("google_sheet_id") and profile.get("google_credentials_path")):
        return None

    # Imported lazily: gspread is only needed when a sheet is configured.
    from src.sheets import get_worksheet

    return get_worksheet(
        profile["google_credentials_path"],
        profile["google_sheet_id"],
        worksheet_gid=profile.get("google_worksheet_gid"),
    )


def run_list(status=None):
    """Print tracked applications."""

    initialize_database()
    applications = get_applications(status=status)

    if not applications:
        print("No applications tracked yet." if not status
              else f"No applications with status {status!r}.")
        return

    for application in applications:
        print(
            f"[{application['status']:<11}] "
            f"{application['company']}: {application['position']}\n"
            f"              {application['apply_url']}"
        )
    print(f"\n{len(applications)} application(s).")


def run_apply(profile_path):
    """Open 'new' applications one at a time, filling what's supported,
    and sync each one's status to your Google Sheet if configured."""

    # Imported lazily: Playwright is only needed for this command.
    from src.applications.autofill import apply_to_listing, load_profile

    initialize_database()
    profile = load_profile(profile_path)
    applications = get_applications(status="new")

    if not applications:
        print("No new applications to open. Run without a subcommand first.")
        return

    worksheet = open_worksheet(profile)
    if worksheet:
        from src.sheets import upsert_application

    print(f"Found {len(applications)} new application(s).")
    start = input("Start going through them? [y/N]: ").strip().lower()

    if start != "y":
        print("Cancelled -- no applications were opened.")
        return

    for application in applications:
        label = f"{application['company']}: {application['position']}"
        url = application["apply_url"]

        choice = input(f"--- {label} ---\nOpen this one? [y/n/q to quit]: ").strip().lower()

        if choice == "q":
            print("Stopping here -- remaining applications are still marked 'new'.")
            break
        if choice != "y":
            continue

        try:
            result = apply_to_listing(url, profile)
        except Exception as error:
            # One page failing to load must not abort the whole session; the
            # application stays 'new' so it can be retried on the next run.
            print(f"Could not process {label}: {error}")
            print("Left as 'new'.")
            continue

        update_status(application["id"], result)

        if worksheet:
            try:
                upsert_application(worksheet, application, result)
            except Exception as error:
                print(f"Saved locally, but the sheet update failed: {error}")
                print("Run `python3 main.py resync` later to push it.")


def run_resync(profile_path):
    """Batch-sync every processed application's status to Google Sheets."""

    from src.applications.autofill import load_profile
    from src.sheets import batch_upsert_applications

    initialize_database()
    profile = load_profile(profile_path)

    worksheet = open_worksheet(profile)
    if worksheet is None:
        print("No Google Sheet configured in profile.json -- nothing to resync.")
        return

    applications = get_applications()
    applications = [a for a in applications if a["status"] != "new"]

    if not applications:
        print("No processed applications to resync yet.")
        return

    print(f"Resyncing {len(applications)} application(s) to the sheet...")

    updated_count, added_count = batch_upsert_applications(
        worksheet,
        applications,
    )

    print(
        f"Done. Updated {updated_count} existing application(s) "
        f"and added {added_count} new application(s)."
    )


def export_csv(matches, path=CSV_PATH):
    """Write matching internships to a CSV file."""

    fieldnames = ["Company", "Position", "Location", "Apply URL"]
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for internship in matches:
            writer.writerow(
                {
                    "Company": internship["company_name"],
                    "Position": internship["title"],
                    "Location": ", ".join(internship["locations"]),
                    "Apply URL": internship["url"],
                }
            )


def print_funnel(funnel):
    """Show how many postings each source lost at each filter stage."""

    width = max([len("source")] + [len(label) for label in funnel])
    print(f"\n{'source':<{width}}  " + "  ".join(f"{s:>8}" for s in FUNNEL_STAGES))
    for label, counts in sorted(funnel.items()):
        print(f"{label:<{width}}  " + "  ".join(f"{counts[s]:>8}" for s in FUNNEL_STAGES))


def run_scan(sources_path, max_age_days):
    """Fetch, filter, deduplicate, store, and export matching internships."""

    print("Fetching internships...")
    internships = fetch_internships(sources_path)
    print(f"Found {len(internships)} total postings.")

    initialize_database()

    # Filter first, deduplicate second: see `deduplicate` for why the order
    # matters. `first_seen` ages out undated postings (Lever) that this
    # scanner has been seeing for longer than the age limit.
    first_seen = get_first_seen_map()
    print_funnel(filter_funnel(internships, max_age_days, first_seen))
    matches = deduplicate(
        filter_internships(
            internships,
            max_age_days=max_age_days,
            first_seen_by_id=first_seen,
        )
    )
    print(f"\nFound {len(matches)} matching internships.\n")

    new_count = save_internships(matches)
    print(f"{new_count} internships were new.")

    export_csv(matches)
    print(f"Saved {len(matches)} matches to {CSV_PATH} successfully!")


def main():
    args = parse_arguments()

    try:
        if args.command == "list":
            run_list(args.status)
        elif args.command == "apply":
            run_apply(args.profile)
        elif args.command == "resync":
            run_resync(args.profile)
        else:
            if args.max_age_days < 0:
                sys.exit("--max-age-days must be zero or greater.")
            run_scan(args.sources, args.max_age_days)
    except FileNotFoundError as error:
        sys.exit(str(error))
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")


if __name__ == "__main__":
    main()
