import { Alert, Input, Modal } from "antd";
import { useEffect, useState } from "react";

interface Props {
  open: boolean;
  title: string;
  okText: string;
  /** Says what the password unlocks, so the prompt is not a bare box. */
  description: string;
  /**
   * Try the action with the password. Resolves `true` when the server accepted
   * it, which the caller uses to close the prompt; `false` keeps it open so the
   * operator can correct a mistyped password.
   */
  onSubmit: (password: string) => Promise<boolean>;
  onCancel: () => void;
}

/**
 * Asks for a protected crawl's deletion password before a write to it (ADR 0042).
 *
 * The password lives in this component's state only: it is cleared when the
 * prompt closes and never written to storage, the URL or a log. It is sent in
 * the `X-Deletion-Password` header by the adapter, and the server checks it on
 * every attempt, so there is no client-side verification to trust.
 */
export function JobPasswordPrompt({
  open,
  title,
  okText,
  description,
  onSubmit,
  onCancel,
}: Props): JSX.Element {
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setPassword("");
      setProblem(null);
    }
  }, [open]);

  async function submit(): Promise<void> {
    if (password === "") {
      setProblem("Enter the crawl's deletion password.");
      return;
    }
    setSubmitting(true);
    setProblem(null);
    try {
      const accepted = await onSubmit(password);
      if (!accepted) {
        setProblem(
          "The password was not accepted, or the action failed. The dashboard shows the reason.",
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      title={title}
      okText={okText}
      confirmLoading={submitting}
      onOk={() => void submit()}
      onCancel={onCancel}
      destroyOnClose
    >
      <p>{description}</p>
      <Input.Password
        id="job-write-password"
        autoComplete="current-password"
        placeholder="Deletion password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        onPressEnter={() => void submit()}
        disabled={submitting}
        autoFocus
      />
      {problem && <Alert type="error" showIcon message={problem} style={{ marginTop: 12 }} />}
    </Modal>
  );
}
