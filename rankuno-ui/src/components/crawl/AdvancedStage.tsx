/**
 * Stage 4: Advanced Options (Accordion/Collapsible Section).
 *
 * Optional fields for proxy, authentication, custom headers, user agent, SSL verification, etc.
 * All fields are optional and Phase 2 (not yet used by crawl engine).
 */

import {
  Alert,
  Checkbox,
  Collapse,
  Form,
  Input,
  Select,
  Switch,
  Tooltip,
  Typography,
} from "antd";
import { InfoCircleOutlined } from "@ant-design/icons";
import { useMemo } from "react";
import type { BasicAuthCredentials } from "../../types/crawlWizard";
import {
  validateProxyUrl,
  validateCustomHeaders,
  validateGA4PropertyId,
} from "../../lib/validation";

interface Props {
  proxy?: string | null;
  useAuth: boolean;
  authUsername?: string;
  authPassword?: string;
  customHeaders?: Record<string, string>;
  userAgent: string;
  verifySsl: boolean;
  gscProperty?: string | null;
  ga4PropertyId?: string | null;
  gscAccounts?: string[];
  gscAccountsLoading?: boolean;
  onProxyChange: (proxy: string | null) => void;
  onAuthToggle: (enabled: boolean) => void;
  onAuthChange: (auth: BasicAuthCredentials | null) => void;
  onHeadersChange: (headers: Record<string, string> | null) => void;
  onUserAgentChange: (ua: string) => void;
  onSSLToggle: (enabled: boolean) => void;
  onGscPropertyChange: (property: string | null) => void;
  onGA4PropertyChange: (id: string | null) => void;
}

const USER_AGENT_PRESETS = [
  { label: "Default (RankunoBot)", value: "RankunoBot" },
  { label: "Chrome Desktop", value: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" },
  { label: "Chrome Mobile", value: "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36" },
  { label: "Firefox Desktop", value: "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0" },
  { label: "Safari Desktop", value: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15" },
];

/**
 * Stage 4: Advanced Options.
 *
 * Accordion with optional configuration for proxy, auth, headers, etc.
 * All fields are Phase 2 (stored but not yet consumed by crawl engine).
 */
export function AdvancedStage({
  proxy,
  useAuth,
  authUsername,
  authPassword,
  customHeaders,
  userAgent,
  verifySsl,
  gscProperty,
  ga4PropertyId,
  gscAccounts,
  gscAccountsLoading,
  onProxyChange,
  onAuthToggle,
  onAuthChange,
  onHeadersChange,
  onUserAgentChange,
  onSSLToggle,
  onGscPropertyChange,
  onGA4PropertyChange,
}: Props): JSX.Element {
  const proxyError = useMemo(() => validateProxyUrl(proxy ?? undefined), [proxy]);
  const headersValidation = useMemo(
    () => validateCustomHeaders(customHeaders ? JSON.stringify(customHeaders) : undefined),
    [customHeaders],
  );
  const ga4Error = useMemo(() => validateGA4PropertyId(ga4PropertyId ?? undefined), [ga4PropertyId]);

  const headersAsString = useMemo(() => {
    if (!customHeaders || Object.keys(customHeaders).length === 0) return "";
    return Object.entries(customHeaders)
      .map(([key, value]) => `${key}: ${value}`)
      .join("\n");
  }, [customHeaders]);

  return (
    <div style={{ paddingBottom: 16 }}>
      <Typography.Title level={4} style={{ marginBottom: 16 }}>
        Advanced options (optional)
      </Typography.Title>

      <Alert
        type="info"
        showIcon
        message="Phase 2 Release"
        description="These options are stored with your crawl but not yet used by the crawl engine. Support will be added in Phase 2C/2D."
        style={{ marginBottom: 16 }}
      />

      <Collapse
        items={[
          {
            key: "proxy",
            label: "Proxy & Network",
            children: (
              <Form layout="vertical">
                <Form.Item
                  label="Use proxy server"
                  valuePropName="checked"
                  style={{ marginBottom: 16 }}
                >
                  <Checkbox
                    checked={!!proxy}
                    onChange={(e) => onProxyChange(e.target.checked ? "" : null)}
                  >
                    Route requests through a proxy
                  </Checkbox>
                </Form.Item>

                {proxy !== null && (
                  <Form.Item
                    label="Proxy URL"
                    validateStatus={proxyError ? "error" : ""}
                    help={proxyError || "Format: socks5://host:port or http://host:port"}
                    required
                  >
                    <Input
                      value={proxy}
                      onChange={(e) => onProxyChange(e.target.value || null)}
                      placeholder="socks5://proxy.example.com:1080"
                    />
                  </Form.Item>
                )}
              </Form>
            ),
          },
          {
            key: "auth",
            label: "Authentication",
            children: (
              <Form layout="vertical">
                <Form.Item
                  label="Basic authentication"
                  valuePropName="checked"
                  style={{ marginBottom: 16 }}
                >
                  <Checkbox checked={useAuth} onChange={(e) => onAuthToggle(e.target.checked)}>
                    Enable basic authentication for target domain
                  </Checkbox>
                </Form.Item>

                {useAuth && (
                  <>
                    <Form.Item label="Username" required>
                      <Input
                        value={authUsername}
                        onChange={(e) =>
                          onAuthChange({
                            username: e.target.value,
                            password: authPassword || "",
                          })
                        }
                        placeholder="username"
                      />
                    </Form.Item>

                    <Form.Item label="Password" required>
                      <Input.Password
                        value={authPassword}
                        onChange={(e) =>
                          onAuthChange({
                            username: authUsername || "",
                            password: e.target.value,
                          })
                        }
                        placeholder="password"
                      />
                    </Form.Item>
                  </>
                )}
              </Form>
            ),
          },
          {
            key: "headers",
            label: "HTTP Headers",
            children: (
              <Form layout="vertical">
                <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
                  Custom HTTP headers to send with every request.
                  <br />
                  Format: one per line as <code>Name: Value</code>, or a JSON object.
                </Typography.Paragraph>

                <Form.Item
                  validateStatus={headersValidation.error ? "error" : ""}
                  help={headersValidation.error}
                >
                  <Input.TextArea
                    value={headersAsString}
                    onChange={(e) => {
                      const validation = validateCustomHeaders(e.target.value);
                      if (validation.error) {
                        // Allow typing, show error on blur or submit
                      } else if (validation.headers) {
                        onHeadersChange(validation.headers);
                      }
                    }}
                    onBlur={(e) => {
                      const validation = validateCustomHeaders(e.target.value);
                      if (!validation.error && validation.headers) {
                        onHeadersChange(validation.headers);
                      }
                    }}
                    placeholder='X-Custom-Header: value&#10;User-Agent: CustomBot'
                    rows={4}
                  />
                </Form.Item>

                {Object.keys(customHeaders || {}).length > 0 && (
                  <div style={{ padding: 8, background: "#f5f5f5", borderRadius: 4 }}>
                    <Typography.Paragraph style={{ fontSize: 11, margin: 0, marginBottom: 4 }}>
                      <strong>Configured headers:</strong>
                    </Typography.Paragraph>
                    {Object.entries(customHeaders || {}).map(([key, value]) => (
                      <div key={key} style={{ fontSize: 11, color: "#666" }}>
                        {key}: {value}
                      </div>
                    ))}
                  </div>
                )}
              </Form>
            ),
          },
          {
            key: "useragent",
            label: "User Agent",
            children: (
              <Form layout="vertical">
                <Form.Item label="User Agent" required>
                  <Select
                    value={userAgent}
                    onChange={onUserAgentChange}
                    options={USER_AGENT_PRESETS}
                    optionRender={(option) => (
                      <span style={{ fontSize: 12 }}>{option.data?.label}</span>
                    )}
                  />
                </Form.Item>

                <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                  The token sent to servers and matched against robots.txt. A descriptive token
                  with contact details allows site owners to permit or block you deliberately.
                </Typography.Paragraph>
              </Form>
            ),
          },
          {
            key: "ssl",
            label: "SSL Verification",
            children: (
              <Form layout="vertical">
                <Form.Item
                  label="Verify SSL certificates"
                  valuePropName="checked"
                  extra={
                    verifySsl
                      ? "Secure. Blocks access to sites with invalid certificates."
                      : "Insecure. Allows self-signed and invalid certificates. Only use on sites you own."
                  }
                >
                  <Switch checked={verifySsl} onChange={onSSLToggle} />
                </Form.Item>
              </Form>
            ),
          },
          {
            key: "enrichment",
            label: "Enrichment (Optional)",
            children: (
              <Form layout="vertical">
                <Form.Item
                  label={
                    <span>
                      Google Search Console property{" "}
                      <Tooltip title="Enriches pages with clicks, impressions, position, CTR from GSC">
                        <InfoCircleOutlined style={{ marginLeft: 4 }} />
                      </Tooltip>
                    </span>
                  }
                >
                  <Input
                    value={gscProperty ?? ""}
                    onChange={(e) => onGscPropertyChange(e.target.value || null)}
                    placeholder="https://example.com (optional)"
                  />
                </Form.Item>

                {gscAccounts && gscAccounts.length > 0 && (
                  <Form.Item
                    label="Search Console account"
                    extra="Which Google account to use for the property above"
                  >
                    <Select
                      disabled={gscAccountsLoading}
                      loading={gscAccountsLoading}
                      virtual={false}
                      options={[
                        { value: "", label: "Default (.env.local)" },
                        ...gscAccounts.map((name) => ({ value: name, label: name })),
                      ]}
                    />
                  </Form.Item>
                )}

                <Form.Item
                  label={
                    <span>
                      GA4 Property ID{" "}
                      <Tooltip title="Enriches pages with GA4 session data">
                        <InfoCircleOutlined style={{ marginLeft: 4 }} />
                      </Tooltip>
                    </span>
                  }
                  validateStatus={ga4Error ? "error" : ""}
                  help={ga4Error || "e.g., 123456789"}
                >
                  <Input
                    value={ga4PropertyId ?? ""}
                    onChange={(e) => onGA4PropertyChange(e.target.value || null)}
                    placeholder="123456789 (optional)"
                  />
                </Form.Item>
              </Form>
            ),
          },
        ]}
        style={{ marginTop: 16 }}
      />
    </div>
  );
}
