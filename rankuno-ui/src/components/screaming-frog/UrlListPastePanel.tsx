import { Alert, Button, Input, Radio } from "antd";
import { useCallback, useEffect, useState } from "react";
import type {
  PasteCounts,
  PastedUrlPlan,
  WorkerDispatchAdapter,
} from "../../adapters/adapterInterface";
import "./screaming-frog.css";

/** A pasted list the operator has checked and chosen a site for. */
export interface PastedListChoice {
  /**
   * The raw text, exactly as pasted and exactly as it was checked.
   *
   * Sent unsplit to the preview, which parses it again with the same parser
   * that produced the numbers below. Two parses of one string by one
   * implementation cannot disagree; a browser-side split and a server-side
   * split could, and the number in the approval would be the one that was
   * wrong.
   */
  urls: string;
  /**
   * The chosen domain's root, offered as the dispatch `seed_url`.
   *
   * A pasted list still needs one: it names the site on the job record, and
   * its registrable domain is the rule every URL is filtered against. With no
   * source crawl to take it from, this is where it comes from — and the
   * operator can still overtype it on the form below.
   */
  seedUrl: string;
}

interface Props {
  /** Needs `planPastedUrlList`; asked for, never assumed. */
  api: WorkerDispatchAdapter | null;
  /**
   * The current complete choice, or `null`.
   *
   * Must be stable across renders — it is an effect dependency one level up.
   */
  onChange: (choice: PastedListChoice | null) => void;
}

/**
 * Paste a list of URLs, and see what would actually be crawled before approving.
 *
 * The third origin for a `--crawl-list` run, and the only one with no crawl
 * behind it: 400 addresses in a spreadsheet that this engine has never seen.
 *
 * Nothing is parsed here. The text is posted to the server, which reads it and
 * answers with the counts and the domains, and the same server parses it again
 * when the preview generates the file. That is the whole reason this panel has
 * a "Check this list" step at all: a browser that counted its own lines would
 * be showing an operator a number that the dispatched file need not have.
 *
 * Two questions the panel exists to answer before the operator commits:
 *
 * * **Which site?** A paste spanning two domains is neither refused nor
 *   silently reduced to the larger one. Both are shown with their counts, the
 *   larger is pre-selected, and choosing one sets the seed URL — whose domain
 *   is what the list is then filtered against. Whatever is not chosen is
 *   excluded and counted in the confirmation dialog.
 * * **What could not be read?** Blank lines, a header row and unreadable lines
 *   are reported here, with the first few quoted back and their line numbers,
 *   so a mistake is found in a spreadsheet rather than in a finished crawl.
 */
export function UrlListPastePanel({ api, onChange }: Props): JSX.Element {
  const [text, setText] = useState("");
  const [plan, setPlan] = useState<PastedUrlPlan | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [domain, setDomain] = useState<string | null>(null);

  // Any edit invalidates the plan and the choice built from it. Left standing,
  // a plan would describe text the operator has since changed, and the seed
  // URL would name a site the pasted list is no longer about.
  function edit(next: string): void {
    setText(next);
    setPlan(null);
    setDomain(null);
    setError(null);
    onChange(null);
  }

  const check = useCallback(async (): Promise<void> => {
    const ask = api?.planPastedUrlList;
    if (!ask) return;
    setChecking(true);
    setError(null);
    setPlan(null);
    setDomain(null);
    onChange(null);
    try {
      const answer = await ask.call(api, text);
      setPlan(answer);
      // Pre-selected, not decided: the largest group is the overwhelmingly
      // common intent, and a form that makes the operator pick when there is
      // only ever one answer teaches them to click past the question.
      const first = answer.domains[0];
      setDomain(first?.registrable_domain ?? null);
      if (first && !answer.exceeds_ceiling) {
        onChange({ urls: text, seedUrl: first.suggested_seed_url });
      }
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not read that list.",
      );
    } finally {
      setChecking(false);
    }
  }, [api, text, onChange]);

  // A paste emptied after a check must not leave a stale offer standing.
  useEffect(() => {
    if (text.trim() === "" && plan !== null) {
      setPlan(null);
      setDomain(null);
    }
  }, [text, plan]);

  function chooseDomain(value: string): void {
    const option = plan?.domains.find((entry) => entry.registrable_domain === value);
    if (!option || plan === null) return;
    setDomain(value);
    onChange(
      plan.exceeds_ceiling ? null : { urls: text, seedUrl: option.suggested_seed_url },
    );
  }

  if (!api?.planPastedUrlList) {
    return (
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 14 }}
        message="This mode cannot check a pasted list, so there is nothing to send."
      />
    );
  }

  return (
    <div className="sfd-list">
      <div className="sfd-field">
        <label htmlFor="sfd-paste">URLs to crawl</label>
        <Input.TextArea
          id="sfd-paste"
          value={text}
          rows={8}
          spellCheck={false}
          placeholder={"https://www.example.com/page-1\nhttps://www.example.com/page-2"}
          aria-describedby="sfd-paste-hint"
          onChange={(event) => edit(event.target.value)}
        />
        <span className="sfd-hint" id="sfd-paste-hint">
          One URL per line. A column copied straight out of a spreadsheet is
          fine — blank lines, a heading row and surrounding quotes are handled,
          and anything that cannot be read is listed below rather than sent.
        </span>
        <Button
          onClick={() => void check()}
          loading={checking}
          disabled={checking || text.trim() === ""}
        >
          Check this list
        </Button>
      </div>

      {error !== null && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 10 }}
          message="Could not read that list."
          description={error}
        />
      )}

      {plan !== null && (
        <>
          <PasteSummary counts={plan.counts} />
          {plan.domains.length === 0 ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 10 }}
              message="No web addresses in that list."
              description="Nothing in the text could be read as a URL, so there is nothing to crawl. Check the lines quoted above."
            />
          ) : (
            <fieldset className="sfd-fieldset">
              <legend>Which site</legend>
              <Radio.Group
                value={domain}
                onChange={(event) => chooseDomain(event.target.value as string)}
              >
                {plan.domains.map((option) => (
                  <Radio
                    key={option.registrable_domain}
                    value={option.registrable_domain}
                    className="sfd-source"
                  >
                    <span className="sfd-source-body">
                      <span className="sfd-source-name">
                        {option.registrable_domain}
                        <span className="sfd-source-count">
                          {` — ${option.url_count.toLocaleString()} URL${
                            option.url_count === 1 ? "" : "s"
                          } before filtering`}
                        </span>
                      </span>
                    </span>
                  </Radio>
                ))}
              </Radio.Group>
              {plan.domains.length > 1 && (
                <p className="sfd-hint">
                  This list covers more than one site, and one crawl can only
                  audit one. The site you pick is the one that runs; the rest
                  are excluded, and the confirmation dialog says how many.
                </p>
              )}
            </fieldset>
          )}
          {plan.exceeds_ceiling && (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 10 }}
              message={`That is more than ${plan.max_urls.toLocaleString()} URLs.`}
              description="The engine refuses an over-long list rather than sending a shortened one, because a shortened list audits fewer pages than the approval says it does. Send fewer URLs, or split the list across more than one run."
            />
          )}
        </>
      )}
    </div>
  );
}

/**
 * What reading the text did, in the order an operator would ask.
 *
 * Every number here is a candidate count from parsing, and the dialog's is the
 * post-filter truth — the same relationship `UrlListSourcePicker`'s counts have
 * to it, and labelled the same way. The unreadable lines are quoted back
 * because a bare "12 could not be read" says there is a problem and nothing
 * about where it is.
 *
 * The quoted lines are rendered as text nodes. They are whatever the operator
 * pasted, echoed by the server verbatim, and have been near no sanitiser.
 */
function PasteSummary({ counts }: { counts: PasteCounts }): JSX.Element {
  const notes: string[] = [];
  if (counts.blank_dropped > 0) {
    notes.push(`${counts.blank_dropped.toLocaleString()} blank line${counts.blank_dropped === 1 ? "" : "s"} ignored`);
  }
  if (counts.header_dropped > 0) notes.push("a heading row ignored");
  if (counts.spreadsheet_rows > 0) {
    notes.push(
      `${counts.spreadsheet_rows.toLocaleString()} spreadsheet row${
        counts.spreadsheet_rows === 1 ? "" : "s"
      } read down to their first address`,
    );
  }
  if (counts.scheme_added > 0) {
    notes.push(
      `${counts.scheme_added.toLocaleString()} address${
        counts.scheme_added === 1 ? "" : "es"
      } had no https:// and were assumed to be https`,
    );
  }
  return (
    <div className="sfd-field" role="status">
      <span className="sfd-source-name">
        {counts.accepted.toLocaleString()} URL{counts.accepted === 1 ? "" : "s"} read
        from {counts.lines.toLocaleString()} line
        {counts.lines === 1 ? "" : "s"}, before filtering
      </span>
      {notes.length > 0 && <span className="sfd-hint">{notes.join("; ")}.</span>}
      {counts.malformed_dropped > 0 && (
        <>
          <span className="sfd-source-why">
            {counts.malformed_dropped.toLocaleString()} line
            {counts.malformed_dropped === 1 ? "" : "s"} could not be read as a web
            address and will not be crawled.
          </span>
          <ul className="sfc-sample">
            {counts.malformed_examples.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
