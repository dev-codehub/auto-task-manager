from __future__ import annotations

import base64
import json
import unittest
import urllib.error
import urllib.request

from jira_sync.client import (AuthError, Client, ForbiddenError, NotFoundError,
                              RejectedError, TransportError)
from tests.fake_jira import demo_fake


class JiraClientTests(unittest.TestCase):
    def setUp(self):
        self.fake = demo_fake().start()
        self.client = Client(self.fake.url, self.fake.email, self.fake.token)

    def tearDown(self):
        self.fake.stop()

    def test_basic_auth_header_carries_email_and_token(self):
        self.client.myself()
        expected = base64.b64encode(b"tester@example.com:test-token").decode("ascii")
        self.assertEqual(self.fake.last_authorization, "Basic " + expected)

    def test_wrong_token_raises_auth_error(self):
        client = Client(self.fake.url, self.fake.email, "wrong-token-value")
        with self.assertRaises(AuthError) as cm:
            client.myself()
        self.assertIn("API token was rejected", str(cm.exception))
        self.assertNotIn("wrong-token-value", str(cm.exception))

    def test_search_follows_every_page(self):
        self.fake.add_issue("Fourth")
        self.fake.add_issue("Fifth")
        found = self.client.search('project = "SCRUM"', ["summary"])
        self.assertEqual(len(found), 5)
        self.assertEqual({i["key"] for i in found},
                         {f"SCRUM-{n}" for n in range(1, 6)})
        searches = [r for r in self.fake.requests if r == "POST /rest/api/3/search/jql"]
        self.assertEqual(len(searches), 3)

    def test_search_is_a_read_and_is_not_recorded_as_a_write(self):
        self.client.search("project = SCRUM", ["summary"])
        self.assertEqual(self.fake.writes, [])

    def test_redirect_is_refused_and_the_token_is_not_followed(self):
        elsewhere = demo_fake().start()
        try:
            self.fake.redirect_to = elsewhere.url + "/rest/api/3/myself"
            with self.assertRaises(TransportError) as cm:
                self.client.myself()
            self.assertIn("redirect", str(cm.exception))
            self.assertEqual(elsewhere.hits, 0)
            self.assertIsNone(elsewhere.last_authorization)
        finally:
            elsewhere.stop()

    def test_html_answer_raises_transport_error_naming_the_url(self):
        self.fake.answer_html = True
        with self.assertRaises(TransportError) as cm:
            self.client.myself()
        self.assertIn("did not answer with JSON", str(cm.exception))
        self.assertIn(self.fake.url, str(cm.exception))

    def test_400_raises_rejected_error_with_jira_message(self):
        with self.assertRaises(RejectedError) as cm:
            self.client.create_issue({"project": {"key": "SCRUM"},
                                      "issuetype": {"name": "Task"}})
        self.assertIn("You must specify a summary", str(cm.exception))

    def test_400_carries_error_messages_too(self):
        with self.assertRaises(RejectedError) as cm:
            self.client.do_transition("SCRUM-1", "999", {})
        self.assertIn("Transition id '999' is not valid", str(cm.exception))

    def test_404_raises_not_found(self):
        with self.assertRaises(NotFoundError):
            self.client.get_issue("SCRUM-999")

    def test_403_raises_forbidden(self):
        self.fake.forbidden.add("SCRUM-1")
        with self.assertRaises(ForbiddenError):
            self.client.update_issue("SCRUM-1", {"summary": "x"})

    def test_http_errors_keep_no_reference_to_the_connection(self):
        with self.assertRaises(NotFoundError) as cm:
            self.client.get_issue("SCRUM-999")
        self.assertIsNone(cm.exception.__context__)

    def test_unreachable_is_transport_error(self):
        with self.assertRaises(TransportError) as cm:
            Client("http://127.0.0.1:1", "a@b.c", "t").myself()
        self.assertIn("cannot reach", str(cm.exception))

    def test_write_and_reread_returns_the_stored_issue_not_the_sent_one(self):
        self.fake.ignored_fields = {"labels"}
        issue = self.client.write_and_reread(
            "SCRUM-1", {"summary": "Renamed", "labels": ["sent"]})
        self.assertEqual(issue["fields"]["summary"], "Renamed")
        self.assertNotIn("labels", issue["fields"])
        self.assertEqual(self.fake.writes,
                         [("PUT", "/rest/api/3/issue/SCRUM-1",
                           {"fields": {"summary": "Renamed", "labels": ["sent"]}})])

    def test_myself_and_project_and_issue_types(self):
        self.assertEqual(self.client.myself()["accountId"], "acc-1")
        self.assertEqual(self.client.get_project("SCRUM")["key"], "SCRUM")
        names = [t["name"] for t in self.client.issue_types("SCRUM")]
        self.assertEqual(names, ["Epic", "Story", "Task", "Sub-task"])

    def test_create_screen_fields(self):
        fields = self.client.create_screen_fields("SCRUM", "10003")
        self.assertEqual([f["fieldId"] for f in fields], ["summary", "description"])
        self.assertTrue(fields[0]["required"])

    def test_createmeta_is_paged_to_the_end(self):
        for n in range(5, 125):
            self.fake.add_issue_type(str(20000 + n), f"Type{n}")
        names = [t["name"] for t in self.client.issue_types("SCRUM")]
        self.assertEqual(len(names), 124)

    def test_create_issue_then_get_issue(self):
        made = self.client.create_issue({"project": {"key": "SCRUM"},
                                         "issuetype": {"name": "Task"},
                                         "summary": "New thing"})
        self.assertEqual(made["key"], "SCRUM-4")
        issue = self.client.get_issue("SCRUM-4")
        self.assertEqual(issue["fields"]["summary"], "New thing")
        self.assertEqual(issue["fields"]["status"]["name"], "To Do")

    def test_comments_round_trip(self):
        adf = {"type": "doc", "version": 1, "content": []}
        added = self.client.add_comment("SCRUM-1", adf)
        self.assertEqual(added["author"]["accountId"], "acc-1")
        self.assertEqual(added["body"], adf)
        self.assertEqual(self.fake.issues["SCRUM-1"]["comments"][0]["body"], adf)
        comments = self.client.list_comments("SCRUM-1")
        self.assertEqual([c["id"] for c in comments], [added["id"]])

    def test_add_comment_without_the_body_wrapper_is_rejected_by_the_fake(self):
        bare = {"type": "doc", "version": 1, "content": []}
        req = urllib.request.Request(
            self.fake.url + "/rest/api/3/issue/SCRUM-1/comment",
            data=json.dumps(bare).encode("utf-8"), method="POST")
        req.add_header("Authorization", "Basic " + base64.b64encode(
            b"tester@example.com:test-token").decode("ascii"))
        req.add_header("Content-Type", "application/json")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)
        cm.exception.close()
        self.assertEqual(self.fake.issues["SCRUM-1"]["comments"], [])

    def test_comments_are_paged_to_the_end(self):
        self.fake.issues["SCRUM-1"]["comments"] = [
            {"id": str(n), "body": {}} for n in range(120)]
        self.assertEqual(len(self.client.list_comments("SCRUM-1")), 120)

    def test_transitions_and_do_transition(self):
        got = self.client.transitions("SCRUM-1")
        self.assertEqual([t["name"] for t in got], ["Start"])
        self.assertIn("transitions.fields", self.fake.queries[-1])
        self.client.do_transition("SCRUM-1", "11", {})
        issue = self.client.get_issue("SCRUM-1")
        self.assertEqual(issue["fields"]["status"]["name"], "In Progress")

    def test_transition_missing_required_field_is_rejected(self):
        self.fake.workflow["To Do"][0]["fields"] = {
            "resolution": {"required": True, "name": "Resolution"}}
        with self.assertRaises(RejectedError):
            self.client.do_transition("SCRUM-1", "11", {})

    def test_fields_link_types_and_links(self):
        self.assertIn("customfield_10016", [f["id"] for f in self.client.list_fields()])
        self.assertEqual(self.client.link_types()[0]["name"], "Blocks")
        self.client.create_link("Blocks", "SCRUM-2", "SCRUM-3")
        links = self.client.get_issue("SCRUM-2")["fields"]["issuelinks"]
        # Inward/outward orientation is unconfirmed until Task 10 checks it on a real site.
        self.assertEqual(links[0]["inwardIssue"]["key"], "SCRUM-3")

    def test_link_with_unknown_type_is_not_found(self):
        with self.assertRaises(NotFoundError):
            self.client.create_link("Nope", "SCRUM-2", "SCRUM-3")


class FakeJiraShapeTests(unittest.TestCase):
    """The fake answers 400 to the payload shapes real Jira rejects, so a client
    that sends the wrong shape fails here instead of in production."""

    def setUp(self):
        self.fake = demo_fake().start()
        self.client = Client(self.fake.url, self.fake.email, self.fake.token)

    def tearDown(self):
        self.fake.stop()

    def raw(self, method, path, body):
        req = urllib.request.Request(self.fake.url + "/rest/api/3" + path,
                                     data=json.dumps(body).encode("utf-8"), method=method)
        req.add_header("Authorization", "Basic " + base64.b64encode(
            b"tester@example.com:test-token").decode("ascii"))
        req.add_header("Content-Type", "application/json")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        cm.exception.close()
        return cm.exception.code

    def test_do_transition_sends_the_transition_id_wrapper(self):
        self.client.do_transition("SCRUM-1", "11", {})
        self.assertEqual(self.fake.writes, [("POST", "/rest/api/3/issue/SCRUM-1/transitions",
                                             {"transition": {"id": "11"}})])

    def test_transition_without_transition_id_is_rejected(self):
        for body in ({"id": "11"}, {"transition": "11"}, {"transition": {}}):
            self.assertEqual(self.raw("POST", "/issue/SCRUM-1/transitions", body), 400, body)
        self.assertEqual(self.fake.issues["SCRUM-1"]["fields"]["status"]["name"], "To Do")

    def test_transition_field_that_is_not_on_its_screen_is_rejected(self):
        with self.assertRaises(RejectedError) as cm:
            self.client.do_transition("SCRUM-1", "11", {"resolution": {"name": "Done"}})
        self.assertIn("resolution", str(cm.exception))
        self.assertEqual(self.fake.issues["SCRUM-1"]["fields"]["status"]["name"], "To Do")

    def test_issue_edit_without_the_fields_wrapper_is_rejected(self):
        self.assertEqual(self.raw("PUT", "/issue/SCRUM-1", {"summary": "x"}), 400)
        self.assertEqual(self.fake.issues["SCRUM-1"]["fields"]["summary"], "Epic one")

    def test_story_points_that_are_not_a_bare_number_are_rejected(self):
        for value in ({"value": 3}, "3", [3]):
            with self.assertRaises(RejectedError, msg=value):
                self.client.update_issue("SCRUM-1", {"customfield_10016": value})
        self.assertNotIn("customfield_10016", self.fake.issues["SCRUM-1"]["fields"])
        self.client.update_issue("SCRUM-1", {"customfield_10016": 3.5})
        self.assertEqual(self.fake.issues["SCRUM-1"]["fields"]["customfield_10016"], 3.5)

    def test_create_without_the_fields_wrapper_or_with_wrong_shapes_is_rejected(self):
        self.fake.create_fields["10003"] += [
            {"fieldId": "priority", "key": "priority", "name": "Priority"},
            {"fieldId": "customfield_10016", "key": "customfield_10016", "name": "Points"}]
        base = {"project": {"key": "SCRUM"}, "issuetype": {"id": "10003"}, "summary": "New"}
        adf = {"type": "doc", "version": 1, "content": []}
        self.assertEqual(self.raw("POST", "/issue", base), 400)
        for extra in ({"description": "plain text, not ADF"}, {"description": {"text": "x"}},
                      {"parent": "SCRUM-1"}, {"parent": {"key": "SCRUM-999"}},
                      {"priority": "High"}, {"customfield_10016": "3"},
                      {"labels": ["not on the create screen"]},
                      {"project": "SCRUM"}, {"issuetype": "10003"}):
            fields = dict(base, **extra)
            self.assertEqual(self.raw("POST", "/issue", {"fields": fields}), 400, extra)
        self.assertEqual(len(self.fake.issues), 3)
        made = self.client.create_issue(dict(base, description=adf, parent={"key": "SCRUM-1"},
                                             priority={"name": "High"},
                                             customfield_10016=3))
        fields = self.fake.issues[made["key"]]["fields"]
        # Read back the way Jira answers: the parent as an object with id and key.
        self.assertEqual(fields["parent"], {"id": self.fake.issues["SCRUM-1"]["id"],
                                            "key": "SCRUM-1"})
        self.assertEqual(fields["description"], adf)

    def test_edit_with_a_wrong_description_parent_or_priority_shape_is_rejected(self):
        for fields in ({"description": "plain"}, {"parent": "SCRUM-1"},
                       {"parent": {"key": "SCRUM-999"}}, {"priority": "High"}):
            self.assertEqual(self.raw("PUT", "/issue/SCRUM-3", {"fields": fields}), 400, fields)
        self.assertNotIn("parent", self.fake.issues["SCRUM-3"]["fields"])
        self.client.update_issue("SCRUM-3", {"parent": {"key": "SCRUM-1"}})
        self.assertEqual(self.fake.issues["SCRUM-3"]["fields"]["parent"]["key"], "SCRUM-1")

    def test_link_with_a_wrong_shape_is_rejected(self):
        good = {"type": {"name": "Blocks"}, "inwardIssue": {"key": "SCRUM-2"},
                "outwardIssue": {"key": "SCRUM-3"}}
        for body in (dict(good, type="Blocks"), dict(good, inwardIssue="SCRUM-2"),
                     {k: v for k, v in good.items() if k != "outwardIssue"},
                     dict(good, outwardIssue={"id": "SCRUM-3"})):
            self.assertEqual(self.raw("POST", "/issueLink", body), 400, body)
        self.assertEqual(self.fake.issues["SCRUM-2"]["fields"]["issuelinks"], [])

    def test_stuck_issue_answers_success_to_a_transition_but_keeps_its_status(self):
        self.fake.stuck.add("SCRUM-1")
        self.client.do_transition("SCRUM-1", "11", {})
        self.assertEqual(self.fake.issues["SCRUM-1"]["fields"]["status"]["name"], "To Do")

    def test_forbidden_covers_comments_and_transitions(self):
        self.fake.forbidden.add("SCRUM-1")
        with self.assertRaises(ForbiddenError):
            self.client.do_transition("SCRUM-1", "11", {})
        with self.assertRaises(ForbiddenError):
            self.client.add_comment("SCRUM-1", {"type": "doc", "version": 1, "content": []})
        self.assertEqual(self.fake.issues["SCRUM-1"]["comments"], [])
        self.assertEqual(self.fake.issues["SCRUM-1"]["fields"]["status"]["name"], "To Do")


if __name__ == "__main__":
    unittest.main()
