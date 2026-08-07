"""robots.txt parsing and crawl-delay extraction (RFC 9309).

Pure logic: this module parses text and answers questions about it. Fetching
`/robots.txt` is a network concern and belongs to a connector in
`src.integrations`. Keeping the two apart is what makes the exclusion rules
exhaustively testable offline.

Why not `urllib.robotparser`
----------------------------
The standard library parser predates RFC 9309 and resolves conflicts by
*declaration order*, whereas the RFC (and every major crawler) resolves them by
*rule specificity* — the longest matching pattern wins, with `Allow` breaking a
tie. On a real site that difference flips the answer:

    Disallow: /resources/
    Allow: /resources/blog/

RFC 9309 permits `/resources/blog/post`; the stdlib parser refuses it. Refusing
2,220 crawlable HighRadius URLs would be a silent, invisible failure.

Pattern matching is deliberately implemented with a linear two-pointer glob
rather than a translated regular expression. robots.txt on a hostile or merely
sloppy host is attacker-influenced input, and a pattern such as
`/*a*a*a*a*a*a*b` compiled to a regex is a catastrophic-backtracking DoS.
"""

from __future__ import annotations

from pydantic import Field

from src.core.schemas import StrictModel

__all__ = [
    "DEFAULT_USER_AGENT",
    "RobotsGroup",
    "RobotsRule",
    "RobotsTxt",
    "parse_robots_txt",
]

DEFAULT_USER_AGENT = "RankunoBot"
"""Product token this platform identifies as. Sites that wish to exclude
Rankuno specifically can target this name."""

_WILDCARD_AGENT = "*"

# A robots.txt served as an HTML error page, or one that is simply enormous, is
# not worth parsing. Both bounds prevent a pathological file from costing more
# than the crawl it governs.
_MAX_LINES = 10_000
_MAX_PATTERN_LENGTH = 2_000


class RobotsRule(StrictModel):
    """A single `Allow` or `Disallow` directive.

    Attributes:
        allow: True for `Allow`, False for `Disallow`.
        pattern: Path pattern. `*` matches any sequence; a trailing `$` anchors
            the match to the end of the path. Otherwise the pattern matches any
            path it prefixes.
    """

    allow: bool
    pattern: str

    @property
    def specificity(self) -> int:
        """Length of the pattern, which RFC 9309 uses to rank competing rules."""
        return len(self.pattern)

    def matches(self, path: str) -> bool:
        """Report whether this rule applies to `path`."""
        return _matches_pattern(self.pattern, path)


class RobotsGroup(StrictModel):
    """The rules attached to one or more user-agent tokens.

    Attributes:
        user_agents: Lowercased product tokens this group governs.
        rules: The group's `Allow` / `Disallow` directives.
        crawl_delay_s: Seconds requested between requests, if the group declares
            a `Crawl-delay`. Non-standard, but widely deployed and honoured here.
    """

    user_agents: tuple[str, ...]
    rules: tuple[RobotsRule, ...] = ()
    crawl_delay_s: float | None = Field(default=None, ge=0.0)


class RobotsTxt(StrictModel):
    """A parsed robots.txt, ready to answer exclusion questions.

    Attributes:
        groups: Every user-agent group found, in declaration order.
        sitemaps: `Sitemap:` URLs. These are file-level, not group-scoped, and
            feed Path A of the 3-path discovery pipeline.
    """

    groups: tuple[RobotsGroup, ...] = ()
    sitemaps: tuple[str, ...] = ()

    def group_for(self, user_agent: str = DEFAULT_USER_AGENT) -> RobotsGroup | None:
        """Select the group governing `user_agent`.

        Applies RFC 9309 §2.2.1: the most specific matching token wins, where a
        token matches when it is a case-insensitive prefix of the crawler's name.
        `*` is the fallback and never beats a named match.

        Args:
            user_agent: The crawler's product token.

        Returns:
            The governing group, or `None` if the file names no applicable group.
        """
        name = user_agent.lower()
        best: RobotsGroup | None = None
        best_length = -1
        fallback: RobotsGroup | None = None

        for group in self.groups:
            for token in group.user_agents:
                if token == _WILDCARD_AGENT:
                    if fallback is None:
                        fallback = group
                    continue
                if name.startswith(token) and len(token) > best_length:
                    best, best_length = group, len(token)

        return best if best is not None else fallback

    def can_fetch(self, path: str, user_agent: str = DEFAULT_USER_AGENT) -> bool:
        """Report whether `path` may be fetched.

        Resolves competing rules by specificity, with `Allow` winning ties —
        the behaviour RFC 9309 §2.2.2 requires and the stdlib parser lacks.

        Args:
            path: Path portion of the target URL, including any query string.
            user_agent: The crawler's product token.

        Returns:
            True when the path is permitted. A file with no applicable rule
            permits everything, which is the specified default.
        """
        group = self.group_for(user_agent)
        if group is None:
            return True

        winner: RobotsRule | None = None
        for rule in group.rules:
            if not rule.matches(path):
                continue
            if winner is None or rule.specificity > winner.specificity:
                winner = rule
            elif rule.specificity == winner.specificity and rule.allow:
                winner = rule  # Allow breaks a tie.

        return True if winner is None else winner.allow

    def crawl_delay(self, user_agent: str = DEFAULT_USER_AGENT) -> float | None:
        """Return the requested delay between requests, if the site declares one.

        Args:
            user_agent: The crawler's product token.

        Returns:
            Seconds to wait between requests, or `None` if unspecified.
        """
        group = self.group_for(user_agent)
        return None if group is None else group.crawl_delay_s


def parse_robots_txt(text: str) -> RobotsTxt:
    """Parse robots.txt source into a queryable object.

    Malformed lines are skipped rather than raising. A syntax error in a remote
    file must not be able to abort a crawl, and the specified failure mode for
    an unparseable directive is to ignore it.

    Args:
        text: Raw robots.txt content.

    Returns:
        The parsed file. Unparseable input yields an empty result, which permits
        everything — matching the specified behaviour for an absent robots.txt.
    """
    groups: list[RobotsGroup] = []
    sitemaps: list[str] = []

    pending_agents: list[str] = []
    rules: list[RobotsRule] = []
    crawl_delay: float | None = None
    # A user-agent line directly after rules starts a new group; one directly
    # after another user-agent line joins the same group.
    accepting_agents = False

    def flush() -> None:
        nonlocal pending_agents, rules, crawl_delay
        if pending_agents:
            groups.append(
                RobotsGroup(
                    user_agents=tuple(pending_agents),
                    rules=tuple(rules),
                    crawl_delay_s=crawl_delay,
                )
            )
        pending_agents, rules, crawl_delay = [], [], None

    for raw_line in text.lstrip("﻿").splitlines()[:_MAX_LINES]:
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue

        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()

        if field == "user-agent":
            if not accepting_agents:
                flush()
                accepting_agents = True
            if value:
                pending_agents.append(value.lower())
            continue

        if field == "sitemap":
            if value:
                sitemaps.append(value)
            continue

        accepting_agents = False

        if field in {"allow", "disallow"}:
            # An empty `Disallow` is the documented way to say "no restriction";
            # recording it as a zero-length pattern would match every path.
            if not value or len(value) > _MAX_PATTERN_LENGTH:
                continue
            rules.append(RobotsRule(allow=field == "allow", pattern=value))
        elif field == "crawl-delay":
            try:
                parsed = float(value)
            except ValueError:
                continue
            if parsed >= 0:
                crawl_delay = parsed

    flush()
    return RobotsTxt(groups=tuple(groups), sitemaps=tuple(sitemaps))


def _matches_pattern(pattern: str, path: str) -> bool:
    """Match a robots.txt path pattern against a path.

    Args:
        pattern: Pattern supporting `*` and a trailing `$`.
        path: The path to test.

    Returns:
        True when the pattern applies.
    """
    if not path.startswith("/"):
        path = "/" + path

    if pattern.endswith("$"):
        return _glob_full_match(pattern[:-1], path)
    # Unanchored patterns match any path they prefix, which is exactly a full
    # match against the pattern with a trailing wildcard appended.
    return _glob_full_match(pattern + "*", path)


def _glob_full_match(pattern: str, text: str) -> bool:
    """Match `text` against `pattern` where `*` means any sequence.

    Iterative two-pointer matching with a single backtrack position. Runs in
    O(len(pattern) * len(text)) worst case and cannot blow up exponentially the
    way a backtracking regular expression can on adversarial input.
    """
    p = t = 0
    star_p = -1
    star_t = 0

    while t < len(text):
        if p < len(pattern) and pattern[p] == text[t]:
            p += 1
            t += 1
        elif p < len(pattern) and pattern[p] == "*":
            star_p = p
            star_t = t
            p += 1
        elif star_p != -1:
            star_t += 1
            t = star_t
            p = star_p + 1
        else:
            return False

    while p < len(pattern) and pattern[p] == "*":
        p += 1
    return p == len(pattern)
