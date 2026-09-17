import { Button, Empty, Popconfirm, Spin, message } from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { useEffect, useState } from "react";
import { API_BASE, ApiError, authorizedFetch } from "../../adapters/httpAdapter";
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

  useEffect(() => {
    void fetchAccounts();
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
