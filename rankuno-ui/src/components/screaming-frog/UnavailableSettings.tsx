import { Collapse } from "antd";
import type { WorkerTemplate } from "../../adapters/adapterInterface";

interface Props {
  /**
   * The template the operator has picked, or `null` for "none".
   *
   * Passed in rather than re-derived here: the view already looks it up from
   * the list it re-reads on every machine change, and a second lookup could
   * disagree with the one under the `<Select>`.
   */
  template: WorkerTemplate | null;
}

/**
 * Where two settings from the old RAE form went, and what to do instead.
 *
 * RAE's New Crawl screen had two pattern textareas and four GA4 fields. Both
 * groups were dead there — `RAE/rankuno-backend/app/api/crawls.py` never
 * forwards `include_patterns` or `exclude_patterns` to the Celery task at all,
 * and `crawl_runner.py` reads none of `ga_account`, `ga4_account`,
 * `ga4_property` or `ga4_stream` while building its argv. Neither can work
 * here either: `FIELD_MAPPING` marks `exclude` `NO_MAPPING` and has no
 * `include` row, because there is no Screaming Frog CLI flag for either, and
 * ADR 0013 condition 5 forbids assuming one exists.
 *
 * So this is a disclosure and not a form. An operator arriving from RAE is
 * looking for a box to type `/admin/` into, and the worst possible answer is
 * to give them one that discards what they type — that is the defect RAE's own
 * documentation confesses to, and it is invisible until a crawl comes back
 * wrong with settings that say it should not have.
 *
 * The Include & Exclude panel earns its place by ending somewhere useful
 * rather than at "we cannot do this": it shows the note a human wrote beside
 * the *currently chosen* template, which is the only account of what that
 * config excludes that can exist — the `.seospiderconfig` is an opaque
 * Java-serialised blob (ADR 0021). Choosing the right template is the real
 * answer to the question the textarea was being asked.
 *
 * Collapsed by default, and antd's `Collapse` header is a real `role="button"`
 * with `aria-expanded` and `aria-controls`, so the panel is reachable and its
 * state announced without anything custom. Everything inside is prose in
 * paragraphs: nothing here is carried by position or colour.
 */
export function UnavailableSettings({ template }: Props): JSX.Element {
  return (
    <section className="sfd-elsewhere" aria-labelledby="sfd-elsewhere-head">
      <h3 id="sfd-elsewhere-head">Settings that are not on this form</h3>
      <Collapse
        ghost
        size="small"
        // Collapsed on arrival. These answer a question an operator only asks
        // once, and opened by default they would push the launch button down
        // the page for everyone who already knows the answer.
        defaultActiveKey={[]}
        items={[
          {
            key: "patterns",
            label: "Include & Exclude — these live in the template, not here",
            children: <PatternsExplanation template={template} />,
          },
          {
            key: "ga4",
            label: "Google Analytics 4 — not connected, and not exported",
            children: <AnalyticsExplanation />,
          },
        ]}
      />
    </section>
  );
}

/** Why there are no pattern boxes, and where the patterns are decided. */
function PatternsExplanation({ template }: { template: WorkerTemplate | null }): JSX.Element {
  return (
    <>
      <p>
        If you came from the old crawl form, this is where the two pattern
        boxes were. Screaming Frog has no command-line setting for include or
        exclude patterns — they are kept inside the configuration file itself,
        and this crawl is started from the command line. A box here could not
        pass on what you typed, so there is no box rather than one that throws
        your patterns away.
      </p>
      <p>
        The patterns are chosen when the template is saved. Someone sets them
        up once in Screaming Frog on the machine that runs the crawl (File,
        then Configuration, then Save As), and picking that template above is
        how you get them. Whoever saved it can leave a note beside it saying
        what it skips, and that note is what you see here.
      </p>
      <TemplateNote template={template} />
    </>
  );
}

/**
 * What the chosen template says about itself.
 *
 * Three outcomes, and the difference between the last two is the one that
 * matters: an empty description means nobody wrote one down, never that the
 * template does nothing. Saying "no patterns" there would be a claim about a
 * binary file this system cannot read.
 */
function TemplateNote({ template }: { template: WorkerTemplate | null }): JSX.Element {
  if (template === null) {
    return (
      <p>
        No template is chosen, so the crawl runs on whatever configuration
        Screaming Frog is already set to on that machine. This screen cannot
        see what that is. Pick a template above to crawl a known configuration.
      </p>
    );
  }
  if (!template.description) {
    return (
      <p>
        Nobody has written a note beside <strong>{template.name}</strong> on
        that machine, so what it includes and excludes is not recorded anywhere
        this screen can read — the configuration file is binary. Open it in
        Screaming Frog on that PC to see, and save a note beside it as{" "}
        <code>{template.name}.md</code> so the next person does not have to.
      </p>
    );
  }
  return (
    <>
      <p>
        What <strong>{template.name}</strong> says about itself:
      </p>
      {/* A text node, never markup. The string is written on a machine outside
          the trust boundary and reaches here through the heartbeat. */}
      <p className="sfd-template-note">{template.description}</p>
    </>
  );
}

/** Why there are no GA4 fields, and why adding four would not be enough. */
function AnalyticsExplanation(): JSX.Element {
  return (
    <>
      <p>
        The old form asked for a Gmail account, a GA4 account, a GA4 property
        and a GA4 data stream. Nothing was ever done with them: they were
        recorded with the crawl and then dropped, so a crawl that looked linked
        to Analytics was not. They are left off this form rather than repeated.
      </p>
      <p>
        Connecting them properly is two jobs, not four boxes. Screaming Frog
        has to be signed in to Google on the machine that runs the crawl, and
        this engine has to ask for the Analytics tab when it collects the
        results — which it does not. So even a working Analytics connection
        would finish the crawl with no Analytics data in the export and nothing
        for a report to read.
      </p>
      <p>
        Until both are done, treat a crawl from this screen as covering the
        site itself and no traffic figures.
      </p>
    </>
  );
}
