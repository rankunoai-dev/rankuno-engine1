"""Tests for the bare URL list reader.

The reader is consulted only after the export loader has refused a file, so its
own failures must be *silent* — an empty grid or `None`, never an exception —
or the user would see a message about the wrong problem. These pin the
defensive branches the happy-path tests in `test_screaming_frog_reconciler`
never reach.
"""

from __future__ import annotations

import pytest
from src.modules.seo.page_classifier.bare_url_list import bare_url_list


class TestNotAList:
    @pytest.mark.parametrize(
        "body",
        [
            pytest.param("", id="empty"),
            pytest.param("   \n\n  \n", id="whitespace-only"),
            pytest.param(b"", id="empty-bytes"),
            # `PK` names a ZIP, and this one is not a workbook. The export
            # loader already refused it with the right message; this must not
            # add a second, wrong one.
            pytest.param(b"PK\x03\x04 not a workbook", id="unreadable-archive"),
            # A bare carriage return inside an unquoted field. `csv.reader`
            # raises mid-iteration, and that has to read as "not a list".
            pytest.param("Title" + chr(10) + "a" + chr(13) + "b,c" + chr(10), id="csv-error"),
            # `urlsplit` raises on an unbalanced IPv6 bracket rather than
            # returning a result, so the URL test must catch it.
            pytest.param("HTML Pages\nhttps://[::1\n", id="unparseable-url"),
            pytest.param("HTML Pages\nftp://e.com/a\n", id="wrong-scheme"),
            pytest.param("HTML Pages\nhttps:///no-host\n", id="no-host"),
            pytest.param("URL,Clicks\nhttps://e.com/a,3\n", id="second-populated-column"),
        ],
    )
    def test_returns_none(self, body):
        assert bare_url_list(body) is None


class TestHeaderDetection:
    def test_a_lone_non_url_first_cell_is_a_header(self):
        assert bare_url_list("Whatever heading\nhttps://e.com/a\n") == ("https://e.com/a",)

    def test_a_url_first_cell_means_headerless(self):
        assert bare_url_list("https://e.com/a\nhttps://e.com/b\n") == (
            "https://e.com/a",
            "https://e.com/b",
        )

    def test_blank_rows_and_surrounding_whitespace_are_ignored(self):
        assert bare_url_list("HTML Pages\n\n  https://e.com/a  \n\n") == ("https://e.com/a",)
