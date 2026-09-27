"""Sync application status to your existing 'Internships' Google Sheet."""

import datetime

import gspread
from google.oauth2.service_account import Credentials

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