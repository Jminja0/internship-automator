import csv
import argparse
import datetime

from src.internships.fetch import fetch_internships
from src.internships.filter import filter_internships
from src.database import (
    initialize_database,
    save_internships,
    get_applications,
    update_status,
)
from src.applications.autofill import apply_to_listing, load_profile
from src.sheets import (
    SOURCE_LABEL,
    STATUS_LABELS,
    get_worksheet,
    upsert_application,
)

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
    """Batch-sync every processed application's status to Google Sheets."""

    initialize_database()
    profile = load_profile(profile_path)

    if not (
        profile.get("google_sheet_id")
        and profile.get("google_credentials_path")
    ):
        print("No Google Sheet configured in profile.json -- nothing to resync.")
        return

    worksheet = get_worksheet(
        profile["google_credentials_path"],
        profile["google_sheet_id"],
        worksheet_gid=profile.get("google_worksheet_gid"),
    )

    applications = [
        application
        for application in get_applications()
        if application["status"] != "new"
    ]

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
def batch_upsert_applications(worksheet, applications):
    """Update and append applications using one Sheets batch request."""

    sheet_values = worksheet.get_all_values()

    # Application URLs are stored in column F, which has index 5.
    url_to_row = {}

    for row_number, row in enumerate(sheet_values, start=1):
        if len(row) > 5 and row[5]:
            url_to_row[row[5].strip()] = row_number

    changes = []
    new_rows = []
    updated_count = 0
    today = datetime.date.today().isoformat()

    for application in applications:
        apply_url = application["apply_url"].strip()
        status_label = STATUS_LABELS.get(
            application["status"],
            application["status"],
        )

        existing_row_number = url_to_row.get(apply_url)

        if existing_row_number:
            existing_row = sheet_values[existing_row_number - 1]
            current_status = (
                existing_row[4]
                if len(existing_row) > 4
                else ""
            )

            # Avoid sending an update when the status is already correct.
            if current_status != status_label:
                changes.append(
                    {
                        "range": f"E{existing_row_number}",
                        "values": [[status_label]],
                    }
                )
                updated_count += 1

            continue

        new_row_number = len(sheet_values) + len(new_rows) + 1

        new_row = [
            application["company"],
            application["position"],
            today,
            SOURCE_LABEL,
            status_label,
            apply_url,
            "",
            "",
            (
                f'=IF(C{new_row_number}="","",'
                f'TODAY()-C{new_row_number})'
            ),
            "",
        ]

        new_rows.append(new_row)

        # Prevent duplicate URLs from being added during the same resync.
        url_to_row[apply_url] = new_row_number

    if new_rows:
        first_new_row = len(sheet_values) + 1
        last_new_row = first_new_row + len(new_rows) - 1

        changes.append(
            {
                "range": f"A{first_new_row}:J{last_new_row}",
                "values": new_rows,
            }
        )

    if changes:
        worksheet.batch_update(
            changes,
            value_input_option="USER_ENTERED",
        )

    return updated_count, len(new_rows)

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