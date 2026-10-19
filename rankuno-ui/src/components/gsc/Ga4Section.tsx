import { Alert, Button, Input, Popconfirm, Select, Space, Spin, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { API_BASE, ApiError, authorizedFetch } from "../../adapters/httpAdapter";

interface Props {
  orgId: string;
}

/** An organisation's GA4 state, as the API returns it. Never a credential. */
interface Ga4View {
  status: "not_configured" | "unmapped" | "mapped";
  property_id: string | null;
}

/** One property the stored GA4 credential can see. */
interface Ga4Property {
  property_id: string;
  display_name: string;
}

/** The picker's answer: a list, or the fixed reason there is none. */
interface Ga4PropertiesView {
  status: "ok" | "not_configured" | "not_authorized" | "unavailable";
  reason: string;
  truncated: boolean;
  properties: Ga4Property[];
}

/** Read a response's `detail` when it is a string, else the status line. */
async function failureMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) return body.detail;
  } catch {
    // Not JSON: fall through to the status line.
  }
  return `${response.status} ${response.statusText}`;
}

async function ga4Call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authorizedFetch(`${API_BASE}${path}`, init);
  if (!response.ok) throw new ApiError(response.status, await failureMessage(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** What the mapping line says, in fixed words, for each state. */
function mappingLine(view: Ga4View): string {
  if (view.status === "mapped") return `Mapped property: ${view.property_id}`;
  if (view.status === "unmapped") {
    return "A GA4 credential is stored. GA4 is not requested until you choose a property.";
  }
  return "No GA4 credential is stored for this organisation.";
}

/**
 * GA4 access for the organisation, shown in the GSC account form (ADR 0038).
 *
 * A separate credential from the Search Console account above it. Collapsed
 * by default, and the status is read only when opened, so opening the account
 * form makes no GA4 request. Every refusal shows the engine's fixed reason
 * text, never a provider message.
 */
export function Ga4Section({ orgId }: Props): JSX.Element {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="ga4-section" style={{ marginTop: 16, borderTop: "1px solid #f0f0f0", paddingTop: 12 }}>
      <Button type="link" style={{ padding: 0 }} aria-expanded={expanded} onClick={() => setExpanded((v) => !v)}>
        {expanded ? "Hide GA4 access" : "Set up GA4 access (optional)"}
      </Button>
      {expanded && <Ga4Body orgId={orgId} />}
    </div>
  );
}

function Ga4Body({ orgId }: Props): JSX.Element {
  const orgPath = `/orgs/${encodeURIComponent(orgId)}/ga4`;
  const [view, setView] = useState<Ga4View | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [listing, setListing] = useState<Ga4PropertiesView | null>(null);
  const [chosen, setChosen] = useState<string | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    ga4Call<Ga4View>(orgPath)
      .then((next) => {
        if (!cancelled) setView(next);
      })
      .catch(() => {
        if (!cancelled) setLoadError("GA4 status could not be loaded.");
      });
    return () => {
      cancelled = true;
    };
  }, [orgPath]);

  async function run(action: () => Promise<void>): Promise<void> {
    setBusy(true);
    try {
      await action();
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "The GA4 request failed.");
    } finally {
      setBusy(false);
    }
  }

  function saveToken(): Promise<void> {
    return run(async () => {
      const next = await ga4Call<Ga4View>(`${orgPath}/credential`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: token }),
      });
      setToken("");
      setView(next);
      setListing(null);
      setChosen(undefined);
      message.success("GA4 access verified and saved. Choose a property next.");
    });
  }

  function loadProperties(): Promise<void> {
    return run(async () => {
      const next = await ga4Call<Ga4PropertiesView>(`${orgPath}/properties`);
      setListing(next);
      setChosen(undefined);
    });
  }

  function saveProperty(): Promise<void> {
    if (!chosen) return Promise.resolve();
    return run(async () => {
      const next = await ga4Call<Ga4View>(`${orgPath}/property`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ property_id: chosen }),
      });
      setView(next);
      message.success(`GA4 property ${chosen} mapped for this organisation.`);
    });
  }

  function removeAccess(): Promise<void> {
    return run(async () => {
      await ga4Call<void>(orgPath, { method: "DELETE" });
      setView({ status: "not_configured", property_id: null });
      setListing(null);
      setChosen(undefined);
      message.success("GA4 access removed.");
    });
  }

  if (loadError) {
    return <Alert type="error" showIcon message={loadError} style={{ marginTop: 12 }} />;
  }
  if (view === null) {
    return <Spin style={{ marginTop: 12 }} />;
  }

  const hasCredential = view.status !== "not_configured";

  return (
    <Space direction="vertical" size={8} style={{ width: "100%", marginTop: 12 }}>
      <Typography.Text>{mappingLine(view)}</Typography.Text>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12, margin: 0 }}>
        GA4 uses its own Google credential, separate from the Search Console account above.
        The token needs the analytics read scope; a token without it is refused.
      </Typography.Paragraph>

      <Input.Password
        aria-label="GA4 refresh token"
        placeholder="GA4 refresh token (write-only)"
        value={token}
        onChange={(event) => setToken(event.target.value)}
        disabled={busy}
      />
      <Button onClick={() => void saveToken()} disabled={busy || token.trim() === ""}>
        Verify and save GA4 token
      </Button>

      <Button onClick={() => void loadProperties()} disabled={busy || !hasCredential}>
        List GA4 properties
      </Button>

      {listing && listing.status !== "ok" && (
        <Alert type="error" showIcon message={listing.reason} />
      )}
      {listing && listing.status === "ok" && (
        <>
          {listing.truncated && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              More properties exist than are listed here.
            </Typography.Text>
          )}
          <Select
            aria-label="GA4 property to map"
            placeholder={listing.properties.length ? "Choose a property" : "No properties are visible to this token"}
            value={chosen}
            onChange={(value) => setChosen(value)}
            disabled={busy || listing.properties.length === 0}
            virtual={false}
            options={listing.properties.map((p) => ({
              value: p.property_id,
              label: `${p.display_name || "Untitled property"} (${p.property_id})`,
            }))}
          />
          <Button onClick={() => void saveProperty()} disabled={busy || !chosen}>
            Map this property
          </Button>
        </>
      )}

      {hasCredential && (
        <Popconfirm
          title="Remove GA4 access?"
          description="The stored GA4 credential and its property mapping are deleted. Crawls stop reading GA4."
          okText="Remove"
          okType="danger"
          cancelText="Cancel"
          onConfirm={() => void removeAccess()}
        >
          <Button danger type="text" disabled={busy}>
            Remove GA4 access
          </Button>
        </Popconfirm>
      )}
    </Space>
  );
}
