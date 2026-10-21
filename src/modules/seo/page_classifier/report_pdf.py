"""The flat PDF of every crawled URL, rendered from the "All URLs" columns.

Split out of `reports.py`, which is at its line ceiling. The PDF is the one
export that is a fixed-layout page rather than a spreadsheet, so it has its own
concerns: landscape pagination, a legend, and wrapping every cell in a
`Paragraph` so a long URL wraps instead of running into its neighbour.

The rows arrive already in category order and carry no separator rows. A
grouped PDF would invite a reader to scan for a heading, and the exports are
meant to be filtered, not navigated.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

from src.modules.seo.contracts.cell_guard import safe_cell

from .fetch_status import (
    STATUS_LEGEND,
    first_redirect_label,
    http_status_label,
)

if TYPE_CHECKING:
    from .schemas import FullPageIntelligenceProfile

__all__ = ["PDF_HEADERS", "pdf_row", "render_url_pdf"]

PDF_HEADERS: tuple[str, ...] = (
    "URL",
    "Hierarchy Level",
    "Page Type",
    "HTTP Status",
    "First Redirect",
    "GSC Clicks",
    "GSC Impressions",
    "GSC CTR %",
    "GSC Avg Position",
    "Depth",
    "Discovery Method",
    "Reachability Tier",
)
"""The twelve legacy "All URLs" columns, in order. Top Queries and Category are
sheet-only and deliberately absent here, so the PDF's contract is unchanged."""

# Points, not inches — reportlab's native unit. Widths favour the free-text
# columns (URL, Discovery Method) and give HTTP Status room for the wrapped
# "Not recorded (older crawl)" label; the rest hold short enums or numbers.
# Sums to 774pt, inside a landscape A4 page's ~806pt usable width after the
# 18pt margins `render_url_pdf` sets.
_PDF_COLUMN_WIDTHS = [150, 66, 66, 62, 48, 42, 56, 40, 52, 34, 88, 70]


def pdf_row(page: FullPageIntelligenceProfile) -> list[str]:
    """The twelve "All URLs" cell values for one page, as guarded plain strings.

    Kept column-for-column with the sheet so the two exports cannot report
    different data for the same job. Each value goes through `safe_cell` as the
    sheet's do, so a URL or category that a spreadsheet would run as a formula is
    neutralised here too, and the two exports cannot disagree about it.
    """
    values = [
        page.url,
        str(page.hierarchy_level),
        str(page.primary_page_type),
        http_status_label(page),
        first_redirect_label(page),
        str(page.gsc_clicks or 0),
        str(page.gsc_impressions or 0),
        f"{(page.gsc_ctr * 100):.2f}" if page.gsc_ctr else "0.00",
        str(page.gsc_avg_position or 0),
        str(page.depth_from_l0) if page.depth_from_l0 is not None else "—",
        str(page.navigation_discovery_method) if page.navigation_discovery_method else "—",
        str(page.navigation_reachability_tier) if page.navigation_reachability_tier else "—",
    ]
    return [str(safe_cell(value)) for value in values]


def render_url_pdf(pages: Sequence[FullPageIntelligenceProfile], banner: str | None) -> BytesIO:
    """Render one row per page, with the partial-data banner above the table when given.

    Landscape A4: twelve columns do not fit a portrait page at a readable size.
    Every cell is a `Paragraph`, not a bare string, because `Table` does not wrap
    plain text and a long URL would overflow into its neighbour.

    Args:
        pages: The pages to list, already in the order they should appear.
        banner: The "GSC data partial" line, or `None` when data is complete.

    Returns:
        The PDF bytes, rewound to the start.
    """
    header_style = ParagraphStyle(
        "pdf-header", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=colors.white
    )
    body_style = ParagraphStyle("pdf-cell", fontName="Helvetica", fontSize=7, leading=9)
    banner_style = ParagraphStyle(
        "pdf-banner",
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#9A3412"),
        spaceAfter=6,
    )

    rows: list[list[Paragraph]] = [
        [Paragraph(_xml_escape(text), header_style) for text in PDF_HEADERS]
    ]
    for page in pages:
        rows.append([Paragraph(_xml_escape(value), body_style) for value in pdf_row(page)])

    table = Table(rows, colWidths=_PDF_COLUMN_WIDTHS, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#366092")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#F2F2F2")],
                ),
            ]
        )
    )

    legend_style = ParagraphStyle(
        "pdf-legend", fontName="Helvetica-Oblique", fontSize=6.5, leading=8, spaceBefore=6
    )
    flowables: list[Paragraph | Table] = []
    if banner:
        flowables.append(Paragraph(_xml_escape(banner), banner_style))
    flowables.append(table)
    flowables.append(Paragraph(_xml_escape(STATUS_LEGEND), legend_style))

    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        leftMargin=18,
        rightMargin=18,
        topMargin=18,
        bottomMargin=18,
    )
    doc.build(flowables)
    output.seek(0)
    return output
