import datetime
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

# The provider unit tests use fake sessions, so they do not require the optional
# HTTP dependency to be installed in the test runner.
if "requests" not in sys.modules:
    requests_stub = types.ModuleType("requests")
    requests_stub.Session = object
    requests_stub.RequestException = Exception
    sys.modules["requests"] = requests_stub

from src import database
from src.internships import fetch
from src.internships.fetch import canonical_url, deduplicate
from src.internships.filter import (
    filter_funnel,
    filter_internships,
    is_recent,
    is_summer_2027,
    is_target_location,
)
from src.internships.providers import ashby, greenhouse, lever
from src.internships.providers.common import text_from_html
from src.sheets import batch_upsert_applications


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload

    def get(self, *args, **kwargs):
        return FakeResponse(self.payload)


class InternshipTests(unittest.TestCase):
    def test_canonical_url_removes_tracking(self):
        self.assertEqual(
            canonical_url("https://example.com/job/1/?utm_source=x&foo=bar#apply"),
            "https://example.com/job/1?foo=bar",
        )

    def test_deduplicate_uses_canonical_url(self):
        jobs = [
            {"company_name": "A", "title": "SWE Intern", "locations": ["Seattle"],
             "url": "https://example.com/1?utm_source=x"},
            {"company_name": "A", "title": "Different", "locations": ["Remote"],
             "url": "https://example.com/1"},
        ]
        self.assertEqual(len(deduplicate(jobs)), 1)

    def test_age_filter(self):
        now = datetime.datetime(2026, 9, 30, tzinfo=datetime.timezone.utc)
        self.assertTrue(is_recent({"posted_at": "2026-09-15T00:00:00Z"}, 30, now))
        self.assertFalse(is_recent({"posted_at": "2026-08-01T00:00:00Z"}, 30, now))
        self.assertTrue(is_recent({"posted_at": None}, 30, now))

    def test_official_feed_accepts_unseasoned_internship(self):
        self.assertTrue(is_summer_2027({
            "source": "greenhouse", "title": "Software Engineering Intern",
            "description": "Current college students", "terms": [],
        }))
        self.assertFalse(is_summer_2027({
            "source": "greenhouse", "title": "Software Intern - Summer 2026",
            "description": "", "terms": [],
        }))

    def test_greenhouse_normalization(self):
        payload = {"jobs": [{"id": 7, "title": "Software Intern 2027",
                              "location": {"name": "Seattle, WA"},
                              "absolute_url": "https://example.com/g/7",
                              "first_published": "2026-09-20T00:00:00Z",
                              "updated_at": "2026-09-21T00:00:00Z",
                              "content": "<p>Summer internship</p>"}]}
        jobs = greenhouse.fetch({"board": "acme", "name": "Acme"}, FakeSession(payload))
        self.assertEqual(jobs[0]["source"], "greenhouse")
        self.assertEqual(jobs[0]["company_name"], "Acme")

    def test_ashby_normalization(self):
        payload = {"jobs": [{"id": "a1", "title": "Software Intern 2027",
                              "location": "United States", "workplaceType": "Remote",
                              "applyUrl": "https://example.com/a/1", "isListed": True,
                              "publishedAt": "2026-09-20T00:00:00Z"}]}
        jobs = ashby.fetch({"board": "acme", "name": "Acme"}, FakeSession(payload))
        self.assertIn("Remote", jobs[0]["locations"])

    def test_lever_normalization_allows_unknown_date(self):
        payload = [{"id": "l1", "text": "Software Intern 2027",
                    "categories": {"location": "Seattle, WA"},
                    "applyUrl": "https://example.com/l/1"}]
        jobs = lever.fetch({"board": "acme", "name": "Acme"}, FakeSession(payload))
        self.assertIsNone(jobs[0]["posted_at"])


def make_job(title="Software Engineer Intern", locations=("Seattle, WA",), **overrides):
    job = {
        "id": title + "|" + "|".join(locations), "source": "greenhouse",
        "company_name": "Acme", "title": title, "locations": list(locations),
        "url": "https://example.com/" + title.replace(" ", "-"),
        "description": "", "terms": [], "category": "", "active": True,
        "posted_at": None,
    }
    job.update(overrides)
    return job


class FilterTests(unittest.TestCase):
    def matches(self, **kwargs):
        return bool(filter_internships([make_job(**kwargs)]))

    def test_full_time_role_is_not_an_internship_because_of_the_word_internal(self):
        self.assertFalse(self.matches(
            title="Senior Software Engineer",
            description="Work with internal teams and international partners.",
        ))

    def test_intern_detected_by_whole_word_in_title(self):
        self.assertTrue(self.matches(title="Software Engineer, Intern"))
        self.assertTrue(self.matches(title="Software Engineer Co-op"))
        self.assertTrue(self.matches(title="Software Engineering Internship"))

    def test_it_intern_at_start_of_title(self):
        self.assertTrue(self.matches(title="IT Intern"))

    def test_bare_years_in_description_do_not_mark_a_job_old(self):
        self.assertTrue(self.matches(description="Copyright 2026 Acme Inc."))

    def test_explicit_old_season_is_rejected(self):
        self.assertFalse(self.matches(description="Join us Summer 2026!"))
        self.assertFalse(self.matches(title="Software Intern - Summer 2026"))
        self.assertTrue(self.matches(title="Software Intern 2027",
                                     description="Summer 2026 recap"))

    def test_location_requires_washington_when_a_state_is_given(self):
        for location in ("Seattle, WA", "Everett, WA", "Seattle", "Seattle, US",
                         "Kent, Washington", "Remote", "Remote - US"):
            self.assertTrue(is_target_location({"locations": [location]}), location)
        for location in ("Everett, MA", "Kent, UK", "Bellevue, NE", "Kentucky",
                         "Louisville, KY", "New York, NY"):
            self.assertFalse(is_target_location({"locations": [location]}), location)

    def test_all_washington_state_locations_are_accepted(self):
        for location in (
            "Spokane, WA", "Vancouver, WA", "Yakima, Washington",
            "Washington State", "Washington, United States", "WA, United States",
        ):
            self.assertTrue(is_target_location({"locations": [location]}), location)

    def test_washington_dc_and_non_washington_locations_are_rejected(self):
        for location in (
            "Washington, DC", "Washington D.C.", "District of Columbia",
            "Vancouver, BC", "Portland, OR",
        ):
            self.assertFalse(is_target_location({"locations": [location]}), location)

    def test_remote_locations_are_accepted(self):
        for location in ("Remote", "Remote - US", "US Remote", "Fully Remote"):
            self.assertTrue(is_target_location({"locations": [location]}), location)

    def test_hidden_simplify_listing_is_excluded(self):
        self.assertFalse(self.matches(
            source="simplify", terms=["Summer 2027"], is_visible=False))
        self.assertTrue(self.matches(
            source="simplify", terms=["Summer 2027"], is_visible=True))

    def test_undated_job_ages_out_by_first_seen(self):
        now = datetime.datetime(2026, 9, 30, tzinfo=datetime.timezone.utc)
        job = {"posted_at": None}
        self.assertTrue(is_recent(job, 30, now))  # never seen: allowed once
        self.assertTrue(is_recent(job, 30, now, first_seen="2026-09-20 12:00:00"))
        self.assertFalse(is_recent(job, 30, now, first_seen="2026-08-01 12:00:00"))

    def test_posted_at_beats_first_seen(self):
        now = datetime.datetime(2026, 9, 30, tzinfo=datetime.timezone.utc)
        job = {"posted_at": "2026-09-25T00:00:00Z"}
        self.assertTrue(is_recent(job, 30, now, first_seen="2026-01-01 00:00:00"))


class FunnelTests(unittest.TestCase):
    def test_funnel_explains_where_each_source_loses_jobs(self):
        jobs = [
            make_job(title="Software Engineer Intern", company_name="Acme"),
            make_job(title="Senior Software Engineer", company_name="Acme"),
            make_job(title="Software Engineer Intern", locations=("Austin, TX",),
                     company_name="Beta"),
            make_job(title="Software Intern", source="simplify",
                     terms=["Summer 2027"], company_name="Gamma"),
        ]
        funnel = filter_funnel(jobs)
        self.assertEqual(funnel["Acme"], {"fetched": 2, "active": 2, "intern": 1,
                                          "software": 1, "location": 1, "recent": 1})
        self.assertEqual(funnel["Beta"]["intern"], 1)
        self.assertEqual(funnel["Beta"]["location"], 0)
        self.assertEqual(funnel["SimplifyJobs"]["recent"], 1)
        total = sum(c["recent"] for c in funnel.values())
        self.assertEqual(total, len(filter_internships(jobs)))


class DeduplicationOrderTests(unittest.TestCase):
    def test_inactive_copy_does_not_shadow_active_copy_when_filtering_first(self):
        inactive_simplify = make_job(
            source="simplify", terms=["Summer 2027"], active=False, id="s1",
            url="https://example.com/job")
        active_official = make_job(id="g1", url="https://example.com/job?utm_source=x")
        result = deduplicate(filter_internships([inactive_simplify, active_official]))
        self.assertEqual([job["id"] for job in result], ["g1"])
        # ...whereas deduplicating first would have lost the job entirely:
        self.assertEqual(
            filter_internships(deduplicate([inactive_simplify, active_official])), [])


class ProviderRobustnessTests(unittest.TestCase):
    def test_html_is_cleaned_whether_raw_or_entity_escaped(self):
        self.assertEqual(text_from_html("<p>Hi <b>there</b></p>"), "Hi there")
        self.assertEqual(text_from_html("&lt;p&gt;Fish &amp;amp; chips&lt;/p&gt;"),
                         "Fish & chips")

    def test_null_fields_from_the_api_do_not_crash(self):
        greenhouse_payload = {"jobs": [{"id": 1, "title": None, "location": None,
                                        "absolute_url": None, "content": None}]}
        jobs = greenhouse.fetch({"board": "b"}, FakeSession(greenhouse_payload))
        self.assertEqual(jobs[0]["locations"], [])

        lever_payload = [{"id": "x", "text": None, "categories": None}]
        jobs = lever.fetch({"board": "b"}, FakeSession(lever_payload))
        self.assertEqual(jobs[0]["title"], "")

        ashby_payload = {"jobs": [{"id": "a", "title": None, "location": None}]}
        jobs = ashby.fetch({"board": "b"}, FakeSession(ashby_payload))
        self.assertEqual(jobs[0]["locations"], [])


class FetchTests(unittest.TestCase):
    def test_one_failing_source_does_not_stop_the_others(self):
        def good(source, session):
            return [make_job(id="ok")]

        def bad(source, session):
            raise AttributeError("unexpected payload shape")

        @contextmanager
        def fake_session():
            yield object()

        sources = [{"provider": "good", "name": "Good"},
                   {"provider": "bad", "name": "Bad"},
                   {"provider": "nope", "name": "Unknown"},
                   {"provider": "good", "name": "Off", "enabled": False}]
        with mock.patch.dict(fetch.PROVIDERS, {"good": good, "bad": bad}), \
                mock.patch.object(fetch, "make_session", fake_session), \
                mock.patch.object(fetch, "load_sources", return_value=sources):
            jobs = fetch.fetch_internships()
        self.assertEqual([job["id"] for job in jobs], ["ok"])

    def test_missing_explicit_sources_file_is_an_error_not_a_silent_fallback(self):
        with self.assertRaises(FileNotFoundError):
            fetch.load_sources("/definitely/not/here.json")


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(
            database, "DATABASE_PATH", Path(self.tmp.name) / "test.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        database.initialize_database()

    def test_save_counts_new_jobs_and_keeps_status_on_rescan(self):
        job = make_job(id="j1")
        self.assertEqual(database.save_internships([job, make_job(id="j2")]), 2)
        database.update_status("j1", "filled")
        self.assertEqual(database.save_internships([job, make_job(id="j3")]), 1)
        statuses = {row["id"]: row["status"] for row in database.get_applications()}
        self.assertEqual(statuses, {"j1": "filled", "j2": "new", "j3": "new"})
        self.assertEqual([r["id"] for r in database.get_applications("filled")], ["j1"])

    def test_first_seen_map_and_empty_save(self):
        self.assertEqual(database.save_internships([]), 0)
        database.save_internships([make_job(id="j1")])
        self.assertIn("j1", database.get_first_seen_map())

    def test_initialize_is_idempotent(self):
        database.initialize_database()
        database.initialize_database()


class FakeWorksheet:
    def __init__(self, values):
        self.values = values
        self.batches = []

    def get_all_values(self):
        return self.values

    def batch_update(self, changes, value_input_option=None):
        self.batches.append((changes, value_input_option))


def app(url, status="filled", company="Acme", position="SWE Intern"):
    return {"apply_url": url, "status": status, "company": company, "position": position}


class SheetsBatchTests(unittest.TestCase):
    def test_updates_changed_status_and_appends_new_rows_in_one_request(self):
        sheet = FakeWorksheet([
            ["Company", "Role", "Date", "Source", "Status", "Link"],
            ["Acme", "SWE", "2026-09-01", "x", "Rejected", "https://a/1"],
            ["Acme", "SWE", "2026-09-01", "x", "Applied", "https://a/2"],
        ])
        updated, added = batch_upsert_applications(sheet, [
            app("https://a/1"), app("https://a/2"), app("https://a/3")])
        self.assertEqual((updated, added), (1, 1))
        self.assertEqual(len(sheet.batches), 1)
        ranges = [change["range"] for change in sheet.batches[0][0]]
        self.assertEqual(ranges, ["E2", "A4:J4"])

    def test_duplicate_url_in_one_resync_does_not_crash_or_double_add(self):
        sheet = FakeWorksheet([["Company"]])
        updated, added = batch_upsert_applications(
            sheet, [app("https://a/1"), app("https://a/1")])
        self.assertEqual((updated, added), (0, 1))

    def test_nothing_to_change_sends_no_request(self):
        sheet = FakeWorksheet([["h"], ["Acme", "SWE", "d", "s", "Applied", "https://a/1"]])
        self.assertEqual(batch_upsert_applications(sheet, [app("https://a/1")]), (0, 0))
        self.assertEqual(sheet.batches, [])


if __name__ == "__main__":
    unittest.main()
