def is_active(internship):
    """Return True if the internship is currently active."""
    return internship.get("active", False)


def is_summer_2027(internship):
    """Return True if the internship includes a Summer 2027 term."""
    terms = internship.get("terms", [])

    return "Summer 2027" in terms


def is_software_related(internship):
    """Return True if the internship is software-related."""
    category = internship.get("category", "").lower()
    title = internship.get("title", "").lower()

    software_categories = {
        "software",
        "software engineering",
    }

    software_keywords = [
        "software",
        "developer",
        "full stack",
        "full-stack",
        "backend",
        "back-end",
        "frontend",
        "front-end",
    ]

    if category in software_categories:
        return True

    return any(keyword in title for keyword in software_keywords)


def is_target_location(internship):
    """Return True for Seattle-area or remote positions."""
    locations = internship.get("locations", [])

    target_locations = [
        "seattle",
        "bellevue",
        "redmond",
        "kirkland",
        "bothell",
        "lynnwood",
    ]

    for location in locations:
        location_lower = location.lower()

        if any(target in location_lower for target in target_locations):
            return True

        if "remote" in location_lower:
            return True

    return False


def filter_internships(internships):
    """Apply all of our internship filters."""

    return [
        internship
        for internship in internships
        if is_active(internship)
        and is_summer_2027(internship)
        and is_software_related(internship)
        and is_target_location(internship)
    ]