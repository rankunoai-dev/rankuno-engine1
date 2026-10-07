import { Alert, Button, Input, Modal, message } from "antd";
import { useState } from "react";

interface Props {
  label: string;
  open: boolean;
  onClose: () => void;
  onConfirm: (password: string) => Promise<void>;
}

/**
 * Modal for permanently deleting a job after confirming the password.
 *
 * Deletion is irreversible and removes all associated data. The operator
 * must type the password that was set when the job was created.
 */
export function DeleteJobModal({
  label,
  open,
  onClose,
  onConfirm,
}: Props): JSX.Element {
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleCancel(): void {
    reset();
    onClose();
  }

  async function handleConfirm(): Promise<void> {
    if (!password.trim()) {
      setError("Password is required");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      await onConfirm(password);
      reset();
      onClose();
      message.success("Crawl deleted");
    } catch (cause) {
      const msg =
        cause instanceof Error
          ? cause.message
          : "The crawl could not be deleted. Please try again.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  function reset(): void {
    setPassword("");
    setError(null);
  }

  return (
    <Modal
      open={open}
      title={`Delete crawl — ${label}`}
      width={500}
      onCancel={handleCancel}
      footer={[
        <Button key="cancel" onClick={handleCancel} disabled={loading}>
          Cancel
        </Button>,
        <Button
          key="delete"
          type="primary"
          danger
          loading={loading}
          disabled={loading || !password.trim()}
          onClick={() => void handleConfirm()}
        >
          Delete
        </Button>,
      ]}
      destroyOnClose
    >
      <Alert
        type="error"
        showIcon
        message="This action is permanent and cannot be undone"
        description="Deletion removes the crawl record, result, checkpoint, and all saved reports."
        style={{ marginBottom: 16 }}
      />

      <div style={{ marginBottom: 16 }}>
        <label htmlFor="delete-password" style={{ display: "block", marginBottom: 8 }}>
          <strong>Enter the job deletion password:</strong>
        </label>
        <Input
          id="delete-password"
          type="password"
          placeholder="Password set at job creation"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={loading}
          onPressEnter={() => void handleConfirm()}
          autoFocus
        />
      </div>

      {error && <Alert type="error" message={error} style={{ marginBottom: 16 }} />}
    </Modal>
  );
}
