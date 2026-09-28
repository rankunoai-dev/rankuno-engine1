"""Tests for the worker-reported template value objects.

The subject here is a string that starts on a machine outside this system's
trust boundary and ends inside an operator's browser. Most of these tests are
about what it is not allowed to be.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.core.worker_templates import (
    MAX_REPORTED_TEMPLATES,
    MAX_TEMPLATE_DESCRIPTION_CHARS,
    WorkerTemplate,
    WorkerTemplateReport,
    normalise_description,
)


class TestWorkerTemplate:
    def test_a_description_is_optional_and_defaults_to_empty(self) -> None:
        """Most templates will never have a sidecar note, and that is fine."""
        assert WorkerTemplate(name="plain").description == ""

    def test_a_name_that_could_become_a_path_component_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            WorkerTemplate(name="../../etc/passwd")

    def test_a_description_at_the_cap_is_accepted(self) -> None:
        template = WorkerTemplate(name="ok", description="x" * MAX_TEMPLATE_DESCRIPTION_CHARS)
        assert len(template.description) == MAX_TEMPLATE_DESCRIPTION_CHARS

    def test_a_description_one_character_over_the_cap_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            WorkerTemplate(name="ok", description="x" * (MAX_TEMPLATE_DESCRIPTION_CHARS + 1))

    @pytest.mark.parametrize(
        ("label", "value"),
        [
            ("bidi override", "safe‮gnp.exe"),
            ("zero width", "in​visible"),
            ("nul byte", "a\x00b"),
            ("newline", "line one\nline two"),
            ("byte order mark", "note﻿"),
        ],
    )
    def test_a_description_that_would_not_render_as_itself_is_refused(
        self, label: str, value: str
    ) -> None:
        """React escapes HTML; nothing escapes a right-to-left override."""
        with pytest.raises(ValidationError):
            WorkerTemplate(name="ok", description=value)
        assert label  # named for the failure message, not asserted on

    def test_the_rejection_message_names_the_problem_and_not_the_value(self) -> None:
        """An error message is a second place untrusted input gets rendered.

        Scoped to `msg` on purpose. Pydantic's own `ValidationError` string
        also carries an `input_value=` echo, which this module does not
        control; that echo only ever travels back to the worker that sent
        the value — the 422 from `POST /workers/heartbeat` — and never into
        an operator's browser, which sees `WorkerTemplatesView` and nothing
        else. The part this module owns must stay value-free so that a log
        line built from `msg` cannot carry a payload.
        """
        with pytest.raises(ValidationError) as caught:
            WorkerTemplate(name="ok", description="attacker‮payload")
        message = caught.value.errors()[0]["msg"]
        assert "attacker" not in message
        assert "bidi-override" in message


class TestWorkerTemplateReport:
    def test_an_empty_report_is_valid_and_means_nothing_was_found(self) -> None:
        report = WorkerTemplateReport()
        assert (report.templates, report.unrecognised_count) == ((), 0)

    def test_the_number_of_templates_is_capped(self) -> None:
        with pytest.raises(ValidationError):
            WorkerTemplateReport(
                templates=tuple(
                    WorkerTemplate(name=f"t{i}") for i in range(MAX_REPORTED_TEMPLATES + 1)
                )
            )

    def test_an_unrecognised_count_beyond_the_cap_is_refused(self) -> None:
        """The daemon saturates it; a hand-built body does not get to exceed it."""
        with pytest.raises(ValidationError):
            WorkerTemplateReport(unrecognised_count=MAX_REPORTED_TEMPLATES + 1)

    def test_a_negative_unrecognised_count_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            WorkerTemplateReport(unrecognised_count=-1)


class TestNormaliseDescription:
    def test_whitespace_is_collapsed_before_controls_are_removed(self) -> None:
        """Order matters: a newline is itself a control character."""
        assert normalise_description("line one\nline two") == "line one line two"

    def test_runs_of_whitespace_become_one_space_and_ends_are_stripped(self) -> None:
        assert normalise_description("  a\t\t  b \n") == "a b"

    def test_a_bidi_override_is_removed_rather_than_rejected(self) -> None:
        """On the worker, a salvageable note is better than no note."""
        assert normalise_description("safe‮gnp.exe") == "safegnp.exe"

    def test_the_result_always_satisfies_the_validator(self) -> None:
        messy = "  what\tthis\n\ncaptures​ ‮ "
        assert WorkerTemplate(name="ok", description=normalise_description(messy))

    def test_it_does_not_truncate_because_the_caller_names_the_template(self) -> None:
        long = "z" * (MAX_TEMPLATE_DESCRIPTION_CHARS + 10)
        assert len(normalise_description(long)) == MAX_TEMPLATE_DESCRIPTION_CHARS + 10
