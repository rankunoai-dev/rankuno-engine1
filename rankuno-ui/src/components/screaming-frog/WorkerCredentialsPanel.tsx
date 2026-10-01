import { Alert, Button, Input, Modal, Popconfirm, Space, Tag, message } from "antd";
import { useState } from "react";
import type {
  WorkerCredentialRotation,
  WorkerDispatchAdapter,
  WorkerSummary,
} from "../../adapters/adapterInterface";

interface Props {
  api: WorkerDispatchAdapter | null;
  workers: WorkerSummary[];
  /** Re-read the fleet after a change, so every view agrees on its state. */
  onChanged: () => void;
}

/**
 * Every registered machine, with the two things an operator can do to its
 * credential: revoke it, or replace it.
 *
 * Methods are always called on the adapter instance (`api.revokeWorker(id)`),
 * never pulled off it first. A detached `HttpAdapter` method loses `this` and
 * fails in production while a mock made of plain functions passes — see
 * `WorkerCredentialsPanel.httpAdapter.test.tsx`.
 *
 * The rotated secret lives in component state only while its dialog is open.
 * Closing the dialog clears it and unmounts the dialog, so the value leaves
 * the DOM too. It is never logged, toasted, or written to a store.
 */
export function WorkerCredentialsPanel({ api, workers, onChanged }: Props): JSX.Element {
  const [pending, setPending] = useState<string | null>(null);
  const [rotation, setRotation] = useState<WorkerCredentialRotation | null>(null);

  const canRevoke = Boolean(api?.revokeWorker);
  const canRotate = Boolean(api?.rotateWorkerCredential);

  async function revoke(worker: WorkerSummary): Promise<void> {
    if (!api?.revokeWorker) return;
    setPending(worker.worker_id);
    try {
      await api.revokeWorker(worker.worker_id);
      void message.success(`${worker.display_name} can no longer connect.`);
      onChanged();
    } catch (cause) {
      void message.error(describe(cause, "Could not revoke that machine."));
    } finally {
      setPending(null);
    }
  }

  async function rotate(worker: WorkerSummary): Promise<void> {
    if (!api?.rotateWorkerCredential) return;
    setPending(worker.worker_id);
    try {
      setRotation(await api.rotateWorkerCredential(worker.worker_id));
      onChanged();
    } catch (cause) {
      void message.error(describe(cause, "Could not issue a new token for that machine."));
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="sfd-card">
      <h3>Registered machines</h3>
      <ul className="sfd-worker-list" aria-label="Registered machines">
        {workers.map((worker) => (
          <li key={worker.worker_id} className="sfd-worker-row">
            <span>
              <strong>{worker.display_name}</strong>{" "}
              <code className="sfd-hint">{worker.worker_id}</code>{" "}
              {worker.is_active ? (
                <Tag color={worker.is_online ? "success" : "default"}>
                  {worker.is_online ? "ONLINE" : "OFFLINE"}
                </Tag>
              ) : (
                <Tag color="error">REVOKED</Tag>
              )}
            </span>
            <span>
              {canRevoke && worker.is_active && (
                <Popconfirm
                  title={`Revoke ${worker.display_name}?`}
                  description="Its token stops working immediately. The worker on that PC stops at its next check-in, and anything it is crawling now cannot be uploaded. Only issuing a new token brings it back."
                  okText="Revoke"
                  okType="danger"
                  cancelText="Cancel"
                  onConfirm={() => void revoke(worker)}
                >
                  <Button
                    size="small"
                    danger
                    aria-label={`Revoke ${worker.display_name}`}
                    loading={pending === worker.worker_id}
                    disabled={pending !== null}
                  >
                    Revoke
                  </Button>
                </Popconfirm>
              )}{" "}
              {canRotate && (
                <Popconfirm
                  title={`Issue a new token for ${worker.display_name}?`}
                  description="The current token stops working immediately. You will be shown the new one once, and must enter it on that PC before the worker can connect again."
                  okText="Issue new token"
                  cancelText="Cancel"
                  onConfirm={() => void rotate(worker)}
                >
                  <Button
                    size="small"
                    aria-label={`Rotate token for ${worker.display_name}`}
                    loading={pending === worker.worker_id}
                    disabled={pending !== null}
                  >
                    Rotate token
                  </Button>
                </Popconfirm>
              )}
            </span>
          </li>
        ))}
      </ul>

      {rotation && (
        <RotatedCredentialModal rotation={rotation} onClose={() => setRotation(null)} />
      )}
    </div>
  );
}

/** The one and only display of a freshly issued secret. */
function RotatedCredentialModal({
  rotation,
  onClose,
}: {
  rotation: WorkerCredentialRotation;
  onClose: () => void;
}): JSX.Element {
  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(rotation.worker_secret);
      void message.success("Token copied.");
    } catch {
      void message.error("Could not copy. Select the token and copy it by hand.");
    }
  }

  return (
    <Modal
      open
      title="New worker token"
      onCancel={onClose}
      maskClosable={false}
      footer={
        <Button type="primary" onClick={onClose}>
          I have saved it, close
        </Button>
      }
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 12 }}
        message="You will not see this token again."
        description="Copy it now and set it as WORKER_CREDENTIAL on that PC, then restart the worker. The old token no longer works."
      />
      <p>
        Machine id (unchanged): <code>{rotation.worker_id}</code>
      </p>
      <Space.Compact style={{ width: "100%" }}>
        <Input
          readOnly
          aria-label="New worker token"
          value={rotation.worker_secret}
          style={{ fontFamily: "monospace" }}
        />
        <Button onClick={() => void copy()}>
          Copy
        </Button>
      </Space.Compact>
    </Modal>
  );
}

function describe(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback;
}
