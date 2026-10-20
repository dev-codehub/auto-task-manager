from __future__ import annotations

import unittest

from jira_sync.adf import adf_lines, markdown_to_adf


def texts(node):
    """Every text string under a node, in order."""
    if node.get("type") == "text":
        return [node["text"]]
    out = []
    for child in node.get("content", []):
        out.extend(texts(child))
    return out


def no_empty_text(test, node):
    if node.get("type") == "text":
        test.assertNotEqual(node["text"], "")
    for child in node.get("content", []):
        no_empty_text(test, child)


class MarkdownToAdfTests(unittest.TestCase):
    def test_headings_paragraphs_lists_code_bold_inline_code_links(self):
        md = (
            "## Title\n"
            "\n"
            "Plain with **bold**, `code` and [site](https://example.com/a).\n"
            "\n"
            "- one\n"
            "- two\n"
            "\n"
            "1. first\n"
            "2. second\n"
            "\n"
            "```python\n"
            "print('x')\n"
            "```\n"
        )
        doc = markdown_to_adf(md)
        self.assertEqual(doc["type"], "doc")
        self.assertEqual(doc["version"], 1)
        kinds = [n["type"] for n in doc["content"]]
        self.assertEqual(
            kinds, ["heading", "paragraph", "bulletList", "orderedList", "codeBlock"]
        )

        heading = doc["content"][0]
        self.assertEqual(heading["attrs"], {"level": 2})
        self.assertEqual(texts(heading), ["Title"])

        para = doc["content"][1]["content"]
        by_text = {n["text"]: n.get("marks") for n in para}
        self.assertEqual(by_text["bold"], [{"type": "strong"}])
        self.assertEqual(by_text["code"], [{"type": "code"}])
        self.assertEqual(
            by_text["site"],
            [{"type": "link", "attrs": {"href": "https://example.com/a"}}],
        )
        self.assertIsNone(by_text["Plain with "])
        self.assertEqual("".join(n["text"] for n in para),
                         "Plain with bold, code and site.")

        bullets = doc["content"][2]
        self.assertEqual([i["type"] for i in bullets["content"]], ["listItem"] * 2)
        self.assertEqual(bullets["content"][0]["content"][0]["type"], "paragraph")
        self.assertEqual(texts(bullets), ["one", "two"])

        ordered = doc["content"][3]
        self.assertEqual(texts(ordered), ["first", "second"])

        code = doc["content"][4]
        self.assertEqual(code["attrs"], {"language": "python"})
        self.assertEqual(texts(code), ["print('x')"])

    def test_heading_levels_one_to_six(self):
        doc = markdown_to_adf("# a\n\n###### f")
        self.assertEqual([n["attrs"]["level"] for n in doc["content"]], [1, 6])

    def test_code_block_without_language_has_no_attrs(self):
        doc = markdown_to_adf("```\nx\n```")
        self.assertNotIn("attrs", doc["content"][0])

    def test_unsupported_markdown_becomes_a_plain_paragraph_never_dropped(self):
        doc = markdown_to_adf("| a | b |\n|---|---|\n| 1 | 2 |")
        self.assertTrue(all(n["type"] == "paragraph" for n in doc["content"]))
        joined = "\n".join(texts(doc))
        self.assertIn("| a | b |", joined)
        self.assertIn("| 1 | 2 |", joined)

    def test_empty_text_gives_a_valid_empty_doc(self):
        for text in ("", "\n\n  \n"):
            self.assertEqual(
                markdown_to_adf(text), {"type": "doc", "version": 1, "content": []}
            )

    def test_unclosed_code_fence_is_closed_at_end(self):
        doc = markdown_to_adf("before\n\n```\nopen line\nmore")
        self.assertEqual(doc["type"], "doc")
        self.assertEqual(doc["version"], 1)
        self.assertIsInstance(doc["content"], list)
        self.assertEqual(doc["content"][-1]["type"], "codeBlock")
        self.assertEqual(texts(doc["content"][-1]), ["open line\nmore"])

    def test_empty_code_fence_emits_no_empty_text_node(self):
        doc = markdown_to_adf("```\n```")
        no_empty_text(self, doc)
        self.assertEqual(doc["content"][0]["type"], "codeBlock")

    def test_adf_lines_round_trips_a_marker_paragraph(self):
        doc = markdown_to_adf("hi\n\n_jira-sync: s_")
        self.assertEqual(adf_lines(doc)[-1], "_jira-sync: s_")
        marker = doc["content"][-1]["content"]
        self.assertEqual(len(marker), 1)
        self.assertNotIn("marks", marker[0])

    def test_adf_lines_one_string_per_paragraph_or_heading(self):
        doc = markdown_to_adf("# H\n\nsome **bold** text\n\n- a\n- b")
        lines = adf_lines(doc)
        self.assertEqual(lines[0], "H")
        self.assertEqual(lines[1], "some bold text")
        self.assertEqual(len(lines), 2)

    def test_adf_lines_of_empty_doc_is_empty(self):
        self.assertEqual(adf_lines(markdown_to_adf("")), [])

    def test_consecutive_lines_join_into_one_paragraph(self):
        doc = markdown_to_adf("one\ntwo\n\nthree")
        self.assertEqual(len(doc["content"]), 2)
        self.assertEqual("".join(texts(doc["content"][0])), "one two")

    def test_bold_and_code_markers_with_nothing_between_are_literal(self):
        doc = markdown_to_adf("a **** b `` c")
        no_empty_text(self, doc)
        self.assertEqual("".join(texts(doc)), "a **** b `` c")

    def test_star_bullets_and_nested_marks_in_list_items(self):
        doc = markdown_to_adf("* **x** y")
        item = doc["content"][0]["content"][0]["content"][0]["content"]
        self.assertEqual(item[0], {"type": "text", "text": "x",
                                   "marks": [{"type": "strong"}]})
        self.assertEqual(item[1]["text"], " y")


if __name__ == "__main__":
    unittest.main()
