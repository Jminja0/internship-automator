import csv

from src.internships.fetch import fetch_internships
from src.internships.filter import filter_internships
from src.database import initialize_database, save_internships


def main():
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