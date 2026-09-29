"""Tests for the bounded-memory array-field extractor (ADR 0023).

The property that matters here is not "it reads JSON" — `json.load` does that.
It is that it reads only the array it was asked for, keeps its window bounded
while doing so, and does not confuse a key of the same name somewhere else in
the document for one of the array's own. That last one is the specific failure
a regular-expression implementation would have, and a real 93 MB crawl result
on this workstation carries 100,736 occurrences of `"url":` for 100,687 pages,
so it is not hypothetical.
"""

from __future__ import annotations

import json

import pytest
from src.core.json_stream import iter_array_object_field


def _write(tmp_path, payload) -> object:
    path = tmp_path / "doc.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestHappyPath:
    def test_yields_each_element_field_in_order(self, tmp_path):
        path = _write(tmp_path, {"pages": [{"url": "a"}, {"url": "b"}, {"url": "c"}]})
        assert list(iter_array_object_field(path, array_key="pages", field="url")) == [
            "a",
            "b",
            "c",
        ]

    def test_keeps_duplicates(self, tmp_path):
        path = _write(tmp_path, {"pages": [{"url": "a"}, {"url": "a"}]})
        assert list(iter_array_object_field(path, array_key="pages", field="url")) == ["a", "a"]

    def test_an_empty_array_yields_nothing(self, tmp_path):
        path = _write(tmp_path, {"pages": []})
        assert list(iter_array_object_field(path, array_key="pages", field="url")) == []

    def test_a_one_element_array(self, tmp_path):
        path = _write(tmp_path, {"pages": [{"url": "only"}]})
        assert list(iter_array_object_field(path, array_key="pages", field="url")) == ["only"]


class TestSelectivity:
    """The reason this is a decoder and not a regular expression."""

    def test_ignores_the_same_key_outside_the_array(self, tmp_path):
        path = _write(
            tmp_path,
            {
                "discovery": {"url": "before"},
                "pages": [{"url": "inside"}],
                "navigation": {"children": [{"url": "after"}]},
            },
        )
        assert list(iter_array_object_field(path, array_key="pages", field="url")) == ["inside"]

    def test_ignores_a_nested_object_carrying_the_same_key(self, tmp_path):
        path = _write(
            tmp_path,
            {"pages": [{"url": "top", "parent": {"url": "nested"}, "signals": [{"url": "deep"}]}]},
        )
        assert list(iter_array_object_field(path, array_key="pages", field="url")) == ["top"]

    def test_a_brace_inside_a_string_does_not_end_the_element(self, tmp_path):
        path = _write(tmp_path, {"pages": [{"url": "a", "note": '}] "url": "fake"'}, {"url": "b"}]})
        assert list(iter_array_object_field(path, array_key="pages", field="url")) == ["a", "b"]

    def test_an_escaped_quote_inside_a_value_survives(self, tmp_path):
        path = _write(tmp_path, {"pages": [{"url": 'a"b'}]})
        assert list(iter_array_object_field(path, array_key="pages", field="url")) == ['a"b']


class TestAbsentOrUnusableValues:
    def test_an_absent_array_key_yields_nothing(self, tmp_path):
        path = _write(tmp_path, {"other": [{"url": "a"}]})
        assert list(iter_array_object_field(path, array_key="pages", field="url")) == []

    def test_an_element_without_the_field_is_skipped_not_fatal(self, tmp_path):
        path = _write(tmp_path, {"pages": [{"url": "a"}, {"canonical_url": "b"}, {"url": "c"}]})
        assert list(iter_array_object_field(path, array_key="pages", field="url")) == ["a", "c"]

    def test_a_non_string_value_is_skipped(self, tmp_path):
        path = _write(tmp_path, {"pages": [{"url": 7}, {"url": None}, {"url": "c"}]})
        assert list(iter_array_object_field(path, array_key="pages", field="url")) == ["c"]

    def test_non_object_elements_are_skipped(self, tmp_path):
        path = _write(tmp_path, {"pages": ["bare", 3, {"url": "c"}]})
        assert list(iter_array_object_field(path, array_key="pages", field="url")) == ["c"]

    def test_a_truncated_file_yields_the_prefix_it_could_decode(self, tmp_path):
        """A partial file is a partial answer, not an exception.

        The caller's own count-and-refuse checks decide whether a short list
        is acceptable; raising here would turn "the crawl is still being
        written" into a 500 rather than into "no URLs yet".
        """
        path = tmp_path / "doc.json"
        path.write_text('{"pages": [{"url": "a"}, {"url": "b"}, {"ur', encoding="utf-8")
        assert list(iter_array_object_field(path, array_key="pages", field="url")) == ["a", "b"]


class TestWindowing:
    @pytest.mark.parametrize("window", [1, 2, 7, 64])
    def test_a_tiny_window_produces_identical_output(self, tmp_path, window):
        """Correctness must not depend on where the read boundaries fall.

        A window of one character forces every refill path in the module —
        mid-key, mid-element, and between elements — to be exercised on a
        document whose expected output is known.
        """
        payload = {
            "lead": {"url": "not-this"},
            "pages": [{"url": f"https://example.com/{n}", "note": "x, y ] }"} for n in range(12)],
            "trail": {"url": "nor-this"},
        }
        path = _write(tmp_path, payload)
        got = list(
            iter_array_object_field(path, array_key="pages", field="url", window_chars=window)
        )
        assert got == [f"https://example.com/{n}" for n in range(12)]

    def test_whitespace_and_indentation_are_tolerated(self, tmp_path):
        path = tmp_path / "doc.json"
        path.write_text(
            json.dumps({"pages": [{"url": "a"}, {"url": "b"}]}, indent=4), encoding="utf-8"
        )
        assert list(iter_array_object_field(path, array_key="pages", field="url")) == ["a", "b"]
