"""Sync application status to your existing 'Internships' Google Sheet."""

import datetime

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

HEADER = [
    "Company", "Role / Position", "Date Applied", "Source", "Status",
    "Application Link", "Contact / Referral", "Follow-up Date",
    "Days Since Applied", "Notes",
]

SOURCE_LABEL = "Summer2027-Internships GitHub repo"

STATUS_LABELS = {
    "filled": "Applied",
    "opened": "Applied",
    "unsupported": "Applied",
}


def get_worksheet(credentials_path, spreadsheet_id, worksheet_gid=None, worksheet_name=None):
    """Open the target tab, preferring its gid (exact) over its name (a guess)."""

    # Imported here so the rest of this module (and the tests) work without
    # the Google libraries installed.
    import gspread
    from google.oauth2.service_account import Credentials

    credentials = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key(spreadsheet_id)

    if worksheet_gid:
        return spreadsheet.get_worksheet_by_id(int(worksheet_gid))

    if worksheet_name:
        return spreadsheet.worksheet(worksheet_name)

    print("No worksheet gid or name given -- using the first tab.")
    return spreadsheet.get_worksheet(0)


def find_row(worksheet, apply_url):
    """Find the row for this application by matching the Application Link column (F)."""
    if not apply_url:
        return None
    cell = worksheet.find(apply_url, in_column=6)
    return cell.row if cell else None


def upsert_application(worksheet, application, status):
    """Update status if the row exists; otherwise append a new row.

    Only ever touches the Status column on an existing row -- your
    notes, referral contacts, and follow-up dates are left alone.
    """

    row_number = find_row(worksheet, application["apply_url"])
    status_label = STATUS_LABELS.get(status, status)

    if row_number:
        worksheet.update(f"E{row_number}", [[status_label]])
        return

    today = datetime.date.today().isoformat()

    # Get the row number where the new application will be added
    new_row_number = len(worksheet.get_all_values()) + 1

    new_row = [
        application["company"],
        application["position"],
        today,
        SOURCE_LABEL,
        status_label,
        application["apply_url"],
        "",
        "",
        f'=IF(C{new_row_number}="","",TODAY()-C{new_row_number})',
        "",
    ]

    worksheet.append_row(
        new_row,
        value_input_option="USER_ENTERED"
    )

def batch_upsert_applications(worksheet, applications):
    """Update and append applications using one Sheets batch request.

    Returns (updated_count, added_count).
    """

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
            # Rows appended earlier in this run aren't in sheet_values yet.
            if existing_row_number > len(sheet_values):
                continue
            existing_row = sheet_values[existing_row_number - 1]
            current_status = existing_row[4] if len(existing_row) > 4 else ""

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

        new_rows.append([
            application["company"],
            application["position"],
            today,
            SOURCE_LABEL,
            status_label,
            apply_url,
            "",
            "",
            f'=IF(C{new_row_number}="","",TODAY()-C{new_row_number})',
            "",
        ])

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
