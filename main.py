import csv
import argparse

from src.internships.fetch import fetch_internships
from src.internships.filter import filter_internships
from src.database import (
    initialize_database,
    save_internships,
    get_applications,
    update_status,
)
from src.applications.autofill import apply_to_listing, load_profile
from src.sheets import get_worksheet, upsert_application

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Find and track internships.")

    parser.add_argument(
        "--filter", 
        action="store_true", 
        help="Filter internships based on criteria.")

    subparsers = parser.add_subparsers(
        dest="command")

    list_parser = subparsers.add_parser(
        "list", 
        help="List all internships.")

    apply_parser = subparsers.add_parser(
        "apply",
        help="Open each new application one at a time and track it.")
    apply_parser.add_argument(
        "--profile",
        default="profile.json",
        help="Path to your profile JSON (see profile.example.json).")

    resync_parser = subparsers.add_parser(
        "resync",
        help="Re-push every processed application's status to the Google Sheet.")
    resync_parser.add_argument(
        "--profile",
        default="profile.json",
        help="Path to your profile JSON (see profile.example.json).")

    return parser.parse_args()


def run_apply(profile_path):
    """Open 'new' applications one at a time, filling what's supported,
    and sync each one's status to your Google Sheet if configured."""

    initialize_database()
    profile = load_profile(profile_path)
    applications = get_applications(status="new")

    if not applications:
        print("No new applications to open. Run without a subcommand first.")
        return

    worksheet = None
    if profile.get("google_sheet_id") and profile.get("google_credentials_path"):
        worksheet = get_worksheet(
            profile["google_credentials_path"],
            profile["google_sheet_id"],
            worksheet_gid=profile.get("google_worksheet_gid"),
        )

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

        result = apply_to_listing(url, profile)
        update_status(application["id"], result)

        if worksheet:
            upsert_application(worksheet, application, result)


def run_resync(profile_path):
    """Re-push every already-processed application's status to the sheet.

    Useful after fixing a Sheets-related bug -- catches up any
    applications whose status was saved locally but never made it
    to the sheet because of an earlier error.
    """

    initialize_database()
    profile = load_profile(profile_path)

    if not (profile.get("google_sheet_id") and profile.get("google_credentials_path")):
        print("No Google Sheet configured in profile.json -- nothing to resync.")
        return

    worksheet = get_worksheet(
        profile["google_credentials_path"],
        profile["google_sheet_id"],
        worksheet_gid=profile.get("google_worksheet_gid"),
    )

    applications = [a for a in get_applications() if a["status"] != "new"]

    if not applications:
        print("No processed applications to resync yet.")
        return

    print(f"Resyncing {len(applications)} application(s) to the sheet...")

    for application in applications:
        upsert_application(worksheet, application, application["status"])

    print("Done.")


def main():
    args = parse_arguments()

    if args.command == "apply":
        run_apply(args.profile)
        return

    if args.command == "resync":
        run_resync(args.profile)
        return

    print(args)
    print("Fetching internships...")

    internships = fetch_internships()

    print(f"Found {len(internships)} total internships.")
    print(type(internships))
    matches = filter_internships(internships)

    print(f"\nFound {len(matches)} matching internships.\n")

    initialize_database()

    new_count = save_internships(matches)

    print(f"{new_count} internships were new.")

    # CSV export
    fieldnames = ["Company", "Position", "Location", "Apply URL"]

    filename = "data/matching_internships.csv"

    with open(filename, "w", newline="", encoding="utf-8") as file:
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

    print(f"Saved {len(matches)} matches to {filename} successfully!")


if __name__ == "__main__":
    main()