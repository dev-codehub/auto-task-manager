from __future__ import annotations

import unittest

from redmine_sync.client import (AuthError, Client, ForbiddenError, NotFoundError,
                                 RejectedError, TransportError)
from tests.fake_redmine import demo_fake


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.fake = demo_fake().start()
        self.client = Client(self.fake.url, self.fake.key)

    def tearDown(self):
        self.fake.stop()

    def test_lists_every_issue_across_pages(self):
        for n in range(1000, 1130):
            self.fake.add_issue(n, f"BULK-{n} filler")
        ids = {i["id"] for i in self.client.list_issues("demo")}
        expected = {i["id"] for i in self.fake.issues.values() if i["project_id"] == 1}
        self.assertEqual(ids, expected)
        self.assertNotIn(201, ids)

    def test_get_project(self):
        self.assertEqual(self.client.get_project("demo")["id"], 1)

    def test_list_statuses(self):
        names = [s["name"] for s in self.client.list_statuses()]
        self.assertEqual(names, ["New", "In Progress", "Resolved", "Closed"])

    def test_get_issue_includes_journals(self):
        self.fake.issues[101]["journals"].append({"id": 1, "notes": "hello"})
        issue = self.client.get_issue(101)
        self.assertEqual(issue["journals"][0]["notes"], "hello")
        self.assertEqual(issue["status"]["name"], "New")

    def test_update_issue(self):
        self.client.update_issue(101, {"notes": "a comment", "done_ratio": 40})
        self.assertEqual(self.fake.issues[101]["done_ratio"], 40)
        self.assertEqual(self.fake.puts, [(101, {"notes": "a comment", "done_ratio": 40})])

    def test_write_and_reread(self):
        issue = self.client.write_and_reread(101, {"done_ratio": 40})
        self.assertEqual(issue["done_ratio"], 40)
        self.assertEqual(self.fake.puts, [(101, {"done_ratio": 40})])

    def test_wrong_key_is_auth_error_without_the_key(self):
        client = Client(self.fake.url, "wrong-key-value")
        with self.assertRaises(AuthError) as cm:
            client.list_statuses()
        self.assertIn("API key was rejected", str(cm.exception))
        self.assertNotIn("wrong-key-value", str(cm.exception))

    def test_forbidden(self):
        self.fake.forbidden.add(101)
        with self.assertRaises(ForbiddenError):
            self.client.update_issue(101, {"notes": "x"})

    def test_not_found(self):
        with self.assertRaises(NotFoundError):
            self.client.get_issue(999)

    def test_http_errors_keep_no_reference_to_the_connection(self):
        with self.assertRaises(NotFoundError) as cm:
            self.client.get_issue(999)
        self.assertIsNone(cm.exception.__context__)
        self.assertIsNone(cm.exception.__cause__)

    def test_non_json_answer_is_transport_error(self):
        self.fake.answer_html = True
        with self.assertRaises(TransportError) as cm:
            self.client.list_statuses()
        self.assertIn("did not answer with JSON", str(cm.exception))

    def test_redirects_are_refused_and_the_key_goes_nowhere_else(self):
        elsewhere = demo_fake(key=self.fake.key).start()
        try:
            self.fake.redirect_to = elsewhere.url + "/issue_statuses.json"
            with self.assertRaises(TransportError) as cm:
                self.client.list_statuses()
            self.assertIn("redirect", str(cm.exception))
            self.assertEqual(elsewhere.hits, 0)
        finally:
            elsewhere.stop()

    def test_current_user(self):
        self.assertEqual(self.client.current_user()["id"], 1)

    def test_server_error_is_transport_error(self):
        self.fake.fail_puts_after = 0
        with self.assertRaises(TransportError):
            self.client.update_issue(101, {"notes": "x"})

    def test_unreachable_is_transport_error(self):
        with self.assertRaises(TransportError) as cm:
            Client("http://127.0.0.1:1", "k").list_statuses()
        self.assertIn("cannot reach", str(cm.exception))

    def test_list_trackers(self):
        names = [t["name"] for t in self.client.list_trackers()]
        self.assertEqual(names, ["User Story", "Task"])

    def test_list_priorities(self):
        names = [p["name"] for p in self.client.list_priorities()]
        self.assertEqual(names, ["Normal", "High"])

    def test_list_versions(self):
        names = [v["name"] for v in self.client.list_versions("demo")]
        self.assertEqual(names, ["P1"])

    def test_list_categories(self):
        names = [c["name"] for c in self.client.list_categories("demo")]
        self.assertEqual(names, ["SUPPORT"])

    def test_list_categories_forbidden_raises(self):
        self.fake.categories_forbidden = True
        with self.assertRaises(ForbiddenError):
            self.client.list_categories("demo")

    def test_create_issue_minimal(self):
        issue = self.client.create_issue(1, {
            "subject": "US-90 A brand new story",
            "description": "text",
            "tracker_id": 1,
            "priority_id": 1,
        })
        self.assertEqual(issue["subject"], "US-90 A brand new story")
        self.assertNotIn("parent", issue)

    def test_create_issue_with_parent_is_readable_back(self):
        created = self.client.create_issue(1, {
            "subject": "US-90.1 A task under 101",
            "description": "text",
            "tracker_id": 2,
            "priority_id": 1,
            "parent_issue_id": 101,
        })
        self.assertEqual(created["parent"]["id"], 101)
        reread = self.client.get_issue(created["id"])
        self.assertEqual(reread["parent"]["id"], 101)

    def test_create_issue_unknown_tracker_rejected(self):
        with self.assertRaises(RejectedError):
            self.client.create_issue(1, {
                "subject": "US-91 Bad tracker", "description": "x",
                "tracker_id": 999, "priority_id": 1,
            })

    def test_create_and_list_relation(self):
        rel = self.client.create_relation(101, 102, "blocks")
        self.assertEqual(rel["relation_type"], "blocks")
        listed = self.client.list_relations(101)
        self.assertEqual([r["relation_type"] for r in listed], ["blocks"])

    def test_create_relation_with_delay(self):
        rel = self.client.create_relation(101, 102, "precedes", delay=3)
        self.assertEqual(rel["delay"], 3)

    def test_create_relation_rejected(self):
        with self.assertRaises(RejectedError):
            self.client.create_relation(101, 101, "blocks")  # self-relation


if __name__ == "__main__":
    unittest.main()
