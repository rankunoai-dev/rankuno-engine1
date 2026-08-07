"""Tests for robots.txt parsing and exclusion decisions."""

from __future__ import annotations

import pytest
from src.core.robots import DEFAULT_USER_AGENT, RobotsRule, parse_robots_txt


class TestParsing:
    def test_empty_input_permits_everything(self):
        robots = parse_robots_txt("")
        assert robots.groups == ()
        assert robots.can_fetch("/anything") is True

    def test_parses_a_simple_group(self):
        robots = parse_robots_txt("User-agent: *\nDisallow: /private/\n")
        assert len(robots.groups) == 1
        assert robots.groups[0].user_agents == ("*",)
        assert robots.can_fetch("/private/x") is False
        assert robots.can_fetch("/public/x") is True

    def test_ignores_comments_and_blank_lines(self):
        robots = parse_robots_txt(
            "# leading comment\n\nUser-agent: *   # trailing\nDisallow: /a/  # why\n\n"
        )
        assert robots.can_fetch("/a/b") is False

    def test_ignores_malformed_lines(self):
        """A syntax error in a remote file must never abort a crawl."""
        robots = parse_robots_txt("this is not a directive\nUser-agent: *\nDisallow: /x\n")
        assert robots.can_fetch("/x") is False

    def test_strips_utf8_bom(self):
        robots = parse_robots_txt("﻿User-agent: *\nDisallow: /x\n")
        assert robots.can_fetch("/x") is False

    def test_field_names_are_case_insensitive(self):
        robots = parse_robots_txt("USER-AGENT: *\nDISALLOW: /x\n")
        assert robots.can_fetch("/x") is False

    def test_empty_disallow_means_no_restriction(self):
        """The documented way to say 'crawl everything'."""
        robots = parse_robots_txt("User-agent: *\nDisallow:\n")
        assert robots.can_fetch("/anything") is True

    def test_consecutive_user_agents_share_one_group(self):
        robots = parse_robots_txt("User-agent: a\nUser-agent: b\nDisallow: /x\n")
        assert len(robots.groups) == 1
        assert robots.groups[0].user_agents == ("a", "b")

    def test_user_agent_after_rules_starts_a_new_group(self):
        robots = parse_robots_txt("User-agent: a\nDisallow: /x\nUser-agent: b\nDisallow: /y\n")
        assert len(robots.groups) == 2

    def test_collects_sitemaps(self):
        robots = parse_robots_txt(
            "Sitemap: https://e.com/sitemap_index.xml\n"
            "User-agent: *\nDisallow: /x\n"
            "Sitemap: https://e.com/news.xml\n"
        )
        assert robots.sitemaps == ("https://e.com/sitemap_index.xml", "https://e.com/news.xml")

    def test_ignores_overlong_patterns(self):
        robots = parse_robots_txt(f"User-agent: *\nDisallow: /{'a' * 5000}\n")
        assert robots.groups[0].rules == ()


class TestUserAgentSelection:
    SOURCE = (
        "User-agent: *\nDisallow: /everyone/\n\n"
        "User-agent: googlebot\nDisallow: /google/\n\n"
        "User-agent: googlebot-news\nDisallow: /news/\n"
    )

    def test_falls_back_to_wildcard_group(self):
        robots = parse_robots_txt(self.SOURCE)
        assert robots.can_fetch("/everyone/x", "RankunoBot") is False
        assert robots.can_fetch("/google/x", "RankunoBot") is True

    def test_named_agent_beats_wildcard(self):
        robots = parse_robots_txt(self.SOURCE)
        assert robots.can_fetch("/google/x", "Googlebot") is False
        assert robots.can_fetch("/everyone/x", "Googlebot") is True, "named group replaces *"

    def test_longest_matching_token_wins(self):
        """Googlebot-News must get its own group, not the shorter 'googlebot' one."""
        robots = parse_robots_txt(self.SOURCE)
        assert robots.can_fetch("/news/x", "Googlebot-News") is False
        assert robots.can_fetch("/google/x", "Googlebot-News") is True

    def test_matching_is_case_insensitive(self):
        robots = parse_robots_txt(self.SOURCE)
        assert robots.can_fetch("/google/x", "GOOGLEBOT") is False

    def test_group_for_returns_none_when_nothing_matches(self):
        robots = parse_robots_txt("User-agent: bingbot\nDisallow: /\n")
        assert robots.group_for("RankunoBot") is None
        assert robots.can_fetch("/anything", "RankunoBot") is True


class TestSpecificityResolution:
    def test_longer_allow_overrides_shorter_disallow(self):
        """The case urllib.robotparser gets wrong. Worth 2,220 HighRadius URLs."""
        robots = parse_robots_txt("User-agent: *\nDisallow: /resources/\nAllow: /resources/blog/\n")
        assert robots.can_fetch("/resources/blog/post") is True
        assert robots.can_fetch("/resources/private/x") is False

    def test_declaration_order_does_not_matter(self):
        forward = parse_robots_txt("User-agent: *\nDisallow: /a/\nAllow: /a/b/\n")
        reverse = parse_robots_txt("User-agent: *\nAllow: /a/b/\nDisallow: /a/\n")
        assert forward.can_fetch("/a/b/c") == reverse.can_fetch("/a/b/c") is True

    def test_allow_wins_an_exact_tie(self):
        robots = parse_robots_txt("User-agent: *\nDisallow: /page\nAllow: /page\n")
        assert robots.can_fetch("/page") is True

    def test_disallow_all(self):
        robots = parse_robots_txt("User-agent: *\nDisallow: /\n")
        assert robots.can_fetch("/") is False
        assert robots.can_fetch("/anything/deep") is False


class TestPatternMatching:
    @pytest.mark.parametrize(
        ("pattern", "path", "expected"),
        [
            ("/foo", "/foo", True),
            ("/foo", "/foobar", True),  # unanchored patterns are prefixes
            ("/foo", "/bar", False),
            ("/foo$", "/foo", True),
            ("/foo$", "/foobar", False),  # $ anchors the end
            ("/*.pdf$", "/docs/a.pdf", True),
            ("/*.pdf$", "/docs/a.pdf?x=1", False),
            ("/a/*/c", "/a/b/c", True),
            ("/a/*/c", "/a/b/d/c", True),
            ("/a/*/c", "/a/c", False),  # both literal slashes are still required
            ("/a*b", "/ab", True),  # * may match an empty sequence
            ("/*?", "/search?q=1", True),
            ("/", "/anything", True),
        ],
    )
    def test_wildcards_and_anchors(self, pattern, path, expected):
        assert RobotsRule(allow=False, pattern=pattern).matches(path) is expected

    def test_path_without_leading_slash_is_normalised(self):
        assert RobotsRule(allow=False, pattern="/foo").matches("foo") is True

    def test_query_string_participates_in_matching(self):
        robots = parse_robots_txt("User-agent: *\nDisallow: /*?sort=\n")
        assert robots.can_fetch("/shop?sort=price") is False
        assert robots.can_fetch("/shop?color=red") is True

    def test_adversarial_pattern_terminates_quickly(self):
        """A regex translation of this would backtrack catastrophically."""
        pattern = "/" + "*a" * 20 + "b$"
        assert RobotsRule(allow=False, pattern=pattern).matches("/" + "a" * 200) is False


class TestCrawlDelay:
    def test_parses_crawl_delay(self):
        robots = parse_robots_txt("User-agent: *\nCrawl-delay: 2.5\nDisallow: /x\n")
        assert robots.crawl_delay() == pytest.approx(2.5)

    def test_absent_crawl_delay_is_none(self):
        assert parse_robots_txt("User-agent: *\nDisallow: /x\n").crawl_delay() is None

    def test_crawl_delay_is_per_group(self):
        robots = parse_robots_txt(
            "User-agent: *\nCrawl-delay: 10\nDisallow:\n\n"
            "User-agent: rankunobot\nCrawl-delay: 1\nDisallow:\n"
        )
        assert robots.crawl_delay(DEFAULT_USER_AGENT) == pytest.approx(1.0)
        assert robots.crawl_delay("OtherBot") == pytest.approx(10.0)

    def test_ignores_non_numeric_crawl_delay(self):
        robots = parse_robots_txt("User-agent: *\nCrawl-delay: soon\nDisallow:\n")
        assert robots.crawl_delay() is None

    def test_ignores_negative_crawl_delay(self):
        robots = parse_robots_txt("User-agent: *\nCrawl-delay: -5\nDisallow:\n")
        assert robots.crawl_delay() is None

    def test_no_matching_group_yields_no_delay(self):
        robots = parse_robots_txt("User-agent: bingbot\nCrawl-delay: 5\nDisallow:\n")
        assert robots.crawl_delay("RankunoBot") is None


class TestRealWorldShape:
    def test_typical_wordpress_robots(self):
        robots = parse_robots_txt(
            "User-agent: *\n"
            "Disallow: /wp-admin/\n"
            "Allow: /wp-admin/admin-ajax.php\n"
            "Disallow: /?s=\n"
            "\n"
            "Sitemap: https://example.com/sitemap_index.xml\n"
        )
        assert robots.can_fetch("/wp-admin/options.php") is False
        assert robots.can_fetch("/wp-admin/admin-ajax.php") is True
        assert robots.can_fetch("/?s=query") is False
        assert robots.can_fetch("/services/consulting/") is True
        assert robots.sitemaps == ("https://example.com/sitemap_index.xml",)
