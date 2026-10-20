import { Collapse } from "antd";
import type { CollapseProps } from "antd";

/**
 * Setup guide for the Search Console and GA4 credentials, shown on the GSC
 * Accounts tab only.
 *
 * Static text, not fetched, so it cannot drift from a server answer. The
 * credential type is an OAuth refresh token, as the account form and the GA4
 * section both require. Google's console menu names are not confirmed from
 * this repository, so each one that is not is marked for checking.
 */

const VERIFY = "verify against current Google Cloud console";

const GCP_CONSOLE = "https://console.cloud.google.com/";
const GCP_API_LIBRARY = "https://console.cloud.google.com/apis/library";
const GCP_CREDENTIALS = "https://console.cloud.google.com/apis/credentials";
const OAUTH_PLAYGROUND = "https://developers.google.com/oauthplayground";
const GA4_DATA_API_DOCS = "https://developers.google.com/analytics/devguides/reporting/data/v1";
const SEARCH_CONSOLE_HELP = "https://support.google.com/webmasters";
const GA4_HELP = "https://support.google.com/analytics";

export interface GuideLink {
  href: string;
  label: string;
}

export interface GuideStep {
  text: string;
  link?: GuideLink;
}

export interface GuideSection {
  key: "gsc" | "ga4";
  title: string;
  steps: readonly GuideStep[];
}

export const GUIDE_HEADER = "Setup guide: Search Console and GA4 credentials";

/** The sections in the order they are read: Search Console first, then GA4. */
export const CREDENTIAL_GUIDE: readonly GuideSection[] = [
  {
    key: "gsc",
    title: "Search Console (GSC) credential",
    steps: [
      {
        text: "Sign in with a Google account that owns the Search Console property, or has been added to it as a user. Rankuno reads only: the scope is https://www.googleapis.com/auth/webmasters.readonly.",
        link: { href: SEARCH_CONSOLE_HELP, label: "Search Console help" },
      },
      {
        text: `Open the Google Cloud console and select the project that will hold the OAuth client (${VERIFY}).`,
        link: { href: GCP_CONSOLE, label: "Google Cloud console" },
      },
      {
        text: `In the API library, enable the Google Search Console API for that project (${VERIFY}).`,
        link: { href: GCP_API_LIBRARY, label: "API library" },
      },
      {
        text: `Configure the OAuth consent screen. For company use inside Google Workspace, choose the internal user type (${VERIFY}).`,
        link: { href: GCP_CONSOLE, label: "Google Cloud console" },
      },
      {
        text: `Create an OAuth client ID under Credentials (${VERIFY}). Keep its client ID and client secret. Both are optional in the account form: leave them blank to use the default client from the server settings.`,
        link: { href: GCP_CREDENTIALS, label: "Credentials" },
      },
      {
        text: "Get an OAuth refresh token that grants the read-only Search Console scope. Google's OAuth playground can do this with your own client. A refresh token is issued only when offline access is requested.",
        link: { href: OAUTH_PLAYGROUND, label: "Google OAuth 2.0 Playground" },
      },
      {
        text: "Click Add Account on this page. Enter an account name (lowercase letters, numbers, hyphens and underscores), paste the refresh token, and add the client ID and secret only if you created your own client.",
      },
      {
        text: "Save. Rankuno does not show the refresh token or the client secret again after saving.",
      },
    ],
  },
  {
    key: "ga4",
    title: "GA4 credential",
    steps: [
      {
        text: `Confirm that the Google account has at least Viewer access to the GA4 property (${VERIFY}).`,
        link: { href: GA4_HELP, label: "Google Analytics help" },
      },
      {
        text: `In the same or another Google Cloud project, enable the Google Analytics Data API (${VERIFY}).`,
        link: { href: GCP_API_LIBRARY, label: "API library" },
      },
      {
        text: "Use the OAuth consent screen and client from the Search Console steps. The same OAuth client can be used for GA4.",
      },
      {
        text: "Get an OAuth refresh token that grants the read-only Analytics scope: https://www.googleapis.com/auth/analytics.readonly. A Search Console token does not carry this scope and is refused.",
        link: { href: GA4_DATA_API_DOCS, label: "Google Analytics Data API documentation" },
      },
      {
        text: "Click Add Account, then expand Set up GA4 access (optional). This GA4 credential belongs to the organisation, not to one Search Console account.",
      },
      {
        text: "Paste the GA4 refresh token and choose Verify and save GA4 token. Rankuno checks the scope before it stores anything.",
      },
      {
        text: "Choose List GA4 properties, pick the property, then choose Map this property. Only properties that the token can see are listed.",
      },
    ],
  },
];

function GuideSteps({ steps }: { steps: readonly GuideStep[] }): JSX.Element {
  return (
    <ol className="gsa-guide-steps">
      {steps.map((step, index) => (
        <li key={index}>
          <span>{step.text}</span>
          {step.link && (
            <>
              {" "}
              <a href={step.link.href} target="_blank" rel="noreferrer noopener">
                {step.link.label}
              </a>
            </>
          )}
        </li>
      ))}
    </ol>
  );
}

function guideItems(): NonNullable<CollapseProps["items"]> {
  return [
    {
      key: "guide",
      label: GUIDE_HEADER,
      children: (
        <div className="gsa-guide">
          {CREDENTIAL_GUIDE.map((section) => (
            <section key={section.key} className="gsa-guide-section" aria-label={section.title}>
              <h3 className="gsa-guide-title">{section.title}</h3>
              <GuideSteps steps={section.steps} />
            </section>
          ))}
        </div>
      ),
    },
  ];
}

/** The collapsed-by-default guide; the account list stays the first thing read. */
export function CredentialSetupGuide(): JSX.Element {
  return (
    <div className="gsa-guide-wrap">
      <Collapse ghost items={guideItems()} />
    </div>
  );
}
