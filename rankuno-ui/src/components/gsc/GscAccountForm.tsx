import { Form, Input, Modal, Spin, message } from "antd";
import type { FormInstance } from "antd";
import { useEffect, useRef, useState } from "react";
import { API_BASE, ApiError, authorizedFetch } from "../../adapters/httpAdapter";
import { Ga4Section } from "./Ga4Section";

/**
 * The part of a saved account the edit form may pre-fill. The secret and the
 * refresh token are write-only on the server and never come back, so they are
 * deliberately absent here: edit mode asks for them again.
 */
export interface EditableGscAccount {
  account_name: string;
  client_id: string | null;
}

interface Props {
  open: boolean;
  orgId: string;
  onClose: () => void;
  onSuccess?: () => void;
  /** When set, the form edits this account in place (same name, replaced credentials). */
  account?: EditableGscAccount | null;
}

interface FormValues {
  account_name: string;
  client_id: string;
  refresh_token: string;
  client_secret?: string;
}

const BLANK_VALUES: FormValues = {
  account_name: "",
  client_id: "",
  refresh_token: "",
  client_secret: "",
};

/**
 * Modal form for adding a new GSC account, or editing a saved one, in an organization.
 *
 * Validates account name against ^[a-z0-9_-]{1,64}$ pattern.
 * Add mode: all fields except client_secret are required.
 * Edit mode: the name is locked, the client ID is pre-filled, and the client
 * secret and refresh token must be entered again because the server cannot
 * return them. The save reuses the existing create route, which replaces an
 * account of the same name (ADR 0016, ADR 0037).
 */
export function GscAccountForm({
  open,
  orgId,
  onClose,
  onSuccess,
  account = null,
}: Props): JSX.Element {
  const [form] = Form.useForm<FormValues>();
  const formRef = useRef<FormInstance>(form);
  const [submitting, setSubmitting] = useState(false);
  const isEdit = account !== null;

  // Pre-fill (edit) or clear (add) each time the form opens, so a previous
  // edit never leaks into the next one.
  useEffect(() => {
    if (!open) return;
    form.resetFields();
    if (account) {
      form.setFieldsValue({
        account_name: account.account_name,
        client_id: account.client_id ?? "",
        refresh_token: "",
        client_secret: "",
      });
    }
  }, [open, account, form]);

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

      message.success(isEdit ? "Account updated successfully" : "Account added successfully");
      form.resetFields();
      onClose();
      onSuccess?.();
    } catch (err) {
      const fallback = isEdit ? "Failed to update account" : "Failed to add account";
      const errorMsg = err instanceof ApiError ? err.message : fallback;
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
      title={isEdit ? "Edit GSC Account" : "Add GSC Account"}
      okText={isEdit ? "Save Changes" : "Add Account"}
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
          initialValues={BLANK_VALUES}
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
            extra={
              isEdit
                ? "The name identifies the account and cannot be changed."
                : "Lowercase letters, numbers, hyphens, and underscores only. 1-64 characters."
            }
          >
            <Input placeholder="my-gsc-account" disabled={isEdit} />
          </Form.Item>

          <Form.Item
            name="refresh_token"
            label="OAuth 2.0 Refresh Token"
            rules={[{ required: true, message: "Enter the OAuth refresh token." }]}
            extra={
              isEdit
                ? "Required. Saved tokens are not shown, so enter it again."
                : "Required. Get this from Google's OAuth flow."
            }
          >
            <Input.Password
              placeholder={
                isEdit
                  ? "Re-enter the refresh token; it must be entered again"
                  : "Paste refresh token here"
              }
            />
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
            rules={
              isEdit
                ? [{ required: true, message: "Enter the OAuth client secret again." }]
                : []
            }
            extra={
              isEdit
                ? "Required. Saved secrets are not shown, so enter it again."
                : "Optional. If not provided, uses the default from settings."
            }
          >
            <Input.Password
              placeholder={
                isEdit
                  ? "Re-enter the client secret; it must be entered again"
                  : "Optional: your OAuth client secret"
              }
            />
          </Form.Item>
        </Form>
      </Spin>
      {/* A separate credential and endpoint set, so it is not part of the
          submit above. Collapsed until opened, so the account form makes no
          GA4 request on open (ADR 0038). */}
      <Ga4Section orgId={orgId} />
    </Modal>
  );
}
