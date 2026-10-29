import { Button, Empty, Popconfirm, Spin, Tooltip, message } from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { useEffect, useState } from "react";
import type { Ga4Mapping } from "../../adapters/adapterInterface";
import { API_BASE, ApiError, authorizedFetch } from "../../adapters/httpAdapter";
import { CredentialSetupGuide } from "./CredentialSetupGuide";
import { GscAccountForm } from "./GscAccountForm";
import "./gsc-accounts.css";

interface GscAccount {
  account_name: string;
  client_id: string | null;
  has_secret_override: boolean;
}

interface Props {
  orgId?: string;
}

/** `null` while loading, `"error"` when the read failed, else the org's answer. */
type Ga4State = Ga4Mapping | "error" | null;

/**
 * Narrows an untrusted response body to `Ga4Mapping`. Anything else is treated
 * as a failed read, so an unknown status can never render as a green or red dot.
 */
function isGa4Mapping(value: unknown): value is Ga4Mapping {
  if (typeof value !== "object" || value === null) return false;
  const status = (value as { status?: unknown }).status;
  return status === "mapped" || status === "unmapped" || status === "not_configured";
}

interface Ga4Display {
  tone: "ok" | "missing" | "muted";
  label: string;
  tooltip: string;
}

/**
 * The fixed words for each GA4 state. Loading and error are grey and say the
 * status is unavailable: neither is a claim that the credential is missing.
 * Unmapped is green because a stored credential with no property chosen is
 * the normal first step, not a fault.
 */
function ga4Display(state: Ga4State): Ga4Display {
  if (state === null) {
    return {
      tone: "muted",
      label: "GA4 status unavailable",
      tooltip: "Checking the GA4 credential for this organisation.",
    };
  }
  if (state === "error") {
    return {
      tone: "muted",
      label: "GA4 status unavailable",
      tooltip: "The GA4 status could not be loaded. Reload the page to try again.",
    };
  }
  if (state.status === "mapped") {
    return {
      tone: "ok",
      label: "GA4 credential stored",
      tooltip: "This organisation has a GA4 credential and a property mapped.",
    };
  }
  if (state.status === "unmapped") {
    return {
      tone: "ok",
      label: "GA4 credential stored",
      tooltip:
        "This organisation has a GA4 credential, but no property is mapped yet. GA4 is not requested until one is chosen.",
    };
  }
  return {
    tone: "missing",
    label: "No GA4 credential",
    tooltip: "This organisation has no GA4 credential stored, so GA4 data cannot be read.",
  };
}

/**
 * One organisation-level GA4 status line, shown above the account list.
 *
 * The dot is decorative: the visible text carries the meaning, so colour is
 * never the only signal. The span is focusable so the tooltip opens on
 * keyboard focus as well as hover.
 */
function Ga4StatusLine({ state }: { state: Ga4State }): JSX.Element {
  const display = ga4Display(state);
  return (
    <div className="gsa-ga4-status" role="status" aria-live="polite">
      {/* antd's default trigger is hover only; focus must open it too. */}
      <Tooltip title={display.tooltip} trigger={["hover", "focus"]}>
        <span className="gsa-ga4-trigger" tabIndex={0}>
          <span className={`gsa-ga4-dot gsa-ga4-dot-${display.tone}`} aria-hidden="true" />
          <span className="gsa-ga4-label">{display.label}</span>
        </span>
      </Tooltip>
    </div>
  );
}

/**
 * View for managing GSC accounts at the organization level.
 *
 * Displays a list of configured accounts with add/delete controls.
 * Uses "default" org if none specified.
 */
export function GscAccountsView({ orgId = "default" }: Props): JSX.Element {
  const [accounts, setAccounts] = useState<GscAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [deleting, setDeleting] = useState<Set<string>>(new Set());
  const [ga4, setGa4] = useState<Ga4State>(null);

  useEffect(() => {
    void fetchAccounts();
  }, [orgId]);

  // One read per page load (and per org change). No polling, and the GA4
  // result never blocks or fails the GSC list above it.
  useEffect(() => {
    let cancelled = false;
    setGa4(null);
    authorizedFetch(`${API_BASE}/orgs/${encodeURIComponent(orgId)}/ga4`)
      .then(async (response) => {
        if (!response.ok) throw new ApiError(response.status, response.statusText);
        const body: unknown = await response.json();
        if (!isGa4Mapping(body)) throw new Error("Unrecognised GA4 status");
        if (!cancelled) setGa4(body);
      })
      .catch(() => {
        if (!cancelled) setGa4("error");
      });
    return () => {
      cancelled = true;
    };
  }, [orgId]);

  async function fetchAccounts(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const response = await authorizedFetch(
        `${API_BASE}/orgs/${encodeURIComponent(orgId)}/gsc-accounts`,
      );

      if (!response.ok) {
        let errorMsg = `${response.status} ${response.statusText}`;
        try {
          const body = (await response.json()) as { detail?: unknown };
          if (typeof body.detail === "string" && body.detail) {
            errorMsg = body.detail;
          }
        } catch {
          // Ignore parse error
        }
        throw new ApiError(response.status, errorMsg);
      }

      const data = (await response.json()) as { accounts: GscAccount[] };
      setAccounts(data.accounts);
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Failed to load accounts";
      setError(msg);
      setAccounts([]);
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(accountName: string): Promise<void> {
    setDeleting((prev) => new Set([...prev, accountName]));
    try {
      const response = await authorizedFetch(
        `${API_BASE}/orgs/${encodeURIComponent(orgId)}/gsc-accounts/${encodeURIComponent(accountName)}`,
        { method: "DELETE" },
      );

      if (!response.ok) {
        let errorMsg = `${response.status} ${response.statusText}`;
        try {
          const body = (await response.json()) as { detail?: unknown };
          if (typeof body.detail === "string" && body.detail) {
            errorMsg = body.detail;
          }
        } catch {
          // Ignore parse error
        }
        throw new ApiError(response.status, errorMsg);
      }

      message.success(`Account "${accountName}" deleted`);
      setAccounts((prev) => prev.filter((a) => a.account_name !== accountName));
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Failed to delete account";
      message.error(msg);
    } finally {
      setDeleting((prev) => {
        const next = new Set(prev);
        next.delete(accountName);
        return next;
      });
    }
  }

  if (error) {
    return (
      <div className="gsa-wrap">
        <div className="gsa-header">
          <h2>GSC Accounts</h2>
        </div>
        <div className="gsa-error">
          <div className="gsa-error-title">Failed to load accounts</div>
          <div className="gsa-error-message">{error}</div>
          <Button onClick={() => void fetchAccounts()} style={{ marginTop: 16 }}>
            Try Again
          </Button>
        </div>
        <CredentialSetupGuide />
      </div>
    );
  }

  return (
    <div className="gsa-wrap">
      <div className="gsa-header">
        <h2>GSC Accounts</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setFormOpen(true)}>
          Add Account
        </Button>
      </div>

      <CredentialSetupGuide />

      <Ga4StatusLine state={ga4} />

      <Spin spinning={loading}>
        {accounts.length === 0 ? (
          <div style={{ textAlign: "center", marginTop: 48 }}>
            <Empty description="No accounts configured" />
            <Button type="primary" onClick={() => setFormOpen(true)} style={{ marginTop: 16 }}>
              Add First Account
            </Button>
          </div>
        ) : (
          <div className="gsa-list">
            {accounts.map((account) => (
              <div key={account.account_name} className="gsa-card">
                <div className="gsa-card-content">
                  <div className="gsa-card-name">{account.account_name}</div>
                  {account.client_id && (
                    <div className="gsa-card-client">
                      <span className="gsa-label">Client ID:</span>
                      <span className="gsa-value">{account.client_id}</span>
                    </div>
                  )}
                  {!account.client_id && (
                    <div className="gsa-card-client">
                      <span className="gsa-label">Client:</span>
                      <span className="gsa-value gsa-default">Using default credentials</span>
                    </div>
                  )}
                  {account.has_secret_override && (
                    <div className="gsa-card-secret">
                      <span className="gsa-label">Secret:</span>
                      <span className="gsa-value gsa-secret">Custom secret configured</span>
                    </div>
                  )}
                </div>
                <Popconfirm
                  title="Delete account?"
                  description={`Are you sure you want to delete "${account.account_name}"? This cannot be undone.`}
                  okText="Delete"
                  okType="danger"
                  cancelText="Cancel"
                  onConfirm={() => void handleDelete(account.account_name)}
                >
                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    loading={deleting.has(account.account_name)}
                    disabled={deleting.size > 0}
                  >
                    Delete
                  </Button>
                </Popconfirm>
              </div>
            ))}
          </div>
        )}
      </Spin>

      <GscAccountForm
        open={formOpen}
        orgId={orgId}
        onClose={() => setFormOpen(false)}
        onSuccess={() => void fetchAccounts()}
      />
    </div>
  );
}
