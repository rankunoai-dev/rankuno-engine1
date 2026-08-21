"""Performance intelligence — Google Search Console and GA4 attached to the crawl.

Pure domain logic. Nothing here opens a socket, reads a file, or touches
FastAPI: ingestion lives in `src/integrations/`, persistence in the job store,
and this package only decides *which crawled page a Google row is about* and
what that means.

The whole pillar rests on one join, and the join is the risk. Search Console
reports a URL it chose, GA4 reports a path its tag saw, and the crawler holds
the address it was linked under. Those three disagree constantly — a redirect,
a canonical tag, a tracking parameter, a trailing slash — and every one of those
disagreements silently drops a page's traffic out of the rollup it belongs to.
`url_identity` exists to make that failure countable instead of invisible.
"""
