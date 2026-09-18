import { Form, Input, Modal, Spin, message } from "antd";
import type { FormInstance } from "antd";
import { useRef, useState } from "react";
import { API_BASE, ApiError, authorizedFetch } from "../../adapters/httpAdapter";

interface Props {
  open: boolean;
  orgId: string;
  onClose: () => void;
  onSuccess?: () => void;
}

interface FormValues {
  account_name: string;
  client_id: string;
  refresh_token: string;
  client_secret?: string;
}

/**
 * Modal form for adding a new GSC account to an organization.
 *
 * Validates account name against ^[a-z0-9_-]{1,64}$ pattern.
 * All fields except client_secret are required.
 */
export function GscAccountForm({ open, orgId, onClose, onSuccess }: Props): JSX.Element {
  const [form] = Form.useForm<FormValues>();
  const formRef = useRef<FormInstance>(form);
  const [submitting, setSubmitting] = useState(false);

  async function submit(): Promise<void> {
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      // Validation failed — errors are rendered in the form items by antd
      return;
    }

    setSubmitting(true);
    try {
      const response = await authorizedFetch(
        `${API_BASE}/orgs/${encodeURIComponent(orgId)}/gsc-accounts`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            account_name: values.account_name,
            client_id: values.client_id || null,
            refresh_token: values.refresh_token,
            client_secret: values.client_secret || null,
          }),
        },
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

      message.success("Account added successfully");
      form.resetFields();
      onClose();
      onSuccess?.();
    } catch (err) {
      const errorMsg = err instanceof ApiError ? err.message : "Failed to add account";
      message.error(errorMsg);
    } finally {
      setSubmitting(false);
    }
  }

  function handleCancel(): void {
    form.resetFields();
    onClose();
  }

  return (
    <Modal
      open={open}
      title="Add GSC Account"
      okText="Add Account"
      cancelText="Cancel"
      onOk={() => void submit()}
      onCancel={handleCancel}
      confirmLoading={submitting}
      destroyOnClose
      width={500}
    >
      <Spin spinning={submitting}>
        <Form
          ref={formRef}
          form={form}
          layout="vertical"
          requiredMark={false}
          initialValues={{
            account_name: "",
            client_id: "",
            refresh_token: "",
            client_secret: "",
          }}
        >
          <Form.Item
            name="account_name"
            label="Account Name"
            rules={[
              { required: true, message: "Enter an account name." },
              {
                pattern: /^[a-z0-9_-]{1,64}$/,
                message: "Must be 1-64 lowercase alphanumeric characters, hyphens, or underscores.",
              },
            ]}
            extra="Lowercase letters, numbers, hyphens, and underscores only. 1-64 characters."
          >
            <Input placeholder="my-gsc-account" />
          </Form.Item>

          <Form.Item
            name="refresh_token"
            label="OAuth 2.0 Refresh Token"
            rules={[{ required: true, message: "Enter the OAuth refresh token." }]}
            extra="Required. Get this from Google's OAuth flow."
          >
            <Input.Password placeholder="Paste refresh token here" />
          </Form.Item>

          <Form.Item
            name="client_id"
            label="OAuth Client ID"
            extra="Optional. If not provided, uses the default from settings."
          >
            <Input placeholder="Optional: your OAuth client ID" />
          </Form.Item>

          <Form.Item
            name="client_secret"
            label="OAuth Client Secret"
            extra="Optional. If not provided, uses the default from settings."
          >
            <Input.Password placeholder="Optional: your OAuth client secret" />
          </Form.Item>
        </Form>
      </Spin>
    </Modal>
  );
}
