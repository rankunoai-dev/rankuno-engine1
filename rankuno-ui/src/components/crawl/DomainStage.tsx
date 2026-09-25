/**
 * Stage 2: Domain Selection.
 *
 * For Full Site: text input for domain with validation.
 * For URL List: dropdown selector showing domains extracted from uploaded URLs.
 */

import { Form, Input, Select, Tooltip, Typography } from "antd";
import { ExclamationCircleOutlined } from "@ant-design/icons";
import { useMemo } from "react";
import type { CrawlSource } from "../../types/crawlWizard";
import type { DomainOption } from "../../types/crawlWizard";
import { extractDomainsWithCounts } from "../../lib/urlParser";
import { validateDomain } from "../../lib/validation";

interface Props {
  source: CrawlSource;
  domain: string;
  uploadedUrls: string[];
  onDomainChange: (domain: string) => void;
}

/**
 * Stage 2: Domain Selection.
 *
 * Shows a text input for Full Site or a dropdown for URL List.
 */
export function DomainStage({ source, domain, uploadedUrls, onDomainChange }: Props): JSX.Element {
  // Extract unique domains with URL counts for URL List source
  const availableDomains = useMemo((): DomainOption[] => {
    return extractDomainsWithCounts(uploadedUrls);
  }, [uploadedUrls]);

  const domainError = useMemo(() => {
    if (domain) return validateDomain(domain);
    return null;
  }, [domain]);

  if (source === "url_list") {
    return (
      <div style={{ paddingBottom: 16 }}>
        <Typography.Title level={4} style={{ marginBottom: 16 }}>
          Which domain should this crawl represent?
        </Typography.Title>

        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 16 }}>
          Select the primary domain from your uploaded URLs. This is used for naming and filtering results.
        </Typography.Paragraph>

        {availableDomains.length === 0 ? (
          <Typography.Paragraph type="danger">
            No valid domains found in uploaded URLs. Please check your file and try again.
          </Typography.Paragraph>
        ) : (
          <Select
            value={domain || undefined}
            onChange={onDomainChange}
            placeholder="Select domain"
            style={{ width: "100%" }}
            options={availableDomains.map((opt) => ({
              value: opt.domain,
              label: (
                <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
                  <span>{opt.domain}</span>
                  <span style={{ color: "#999", fontSize: 12 }}>
                    {opt.urlCount} URL{opt.urlCount !== 1 ? "s" : ""}
                  </span>
                </div>
              ),
            }))}
          />
        )}

        {availableDomains.length > 0 && (
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12 }}>
            Total URLs: <strong>{uploadedUrls.length}</strong>
          </Typography.Paragraph>
        )}
      </div>
    );
  }

  // Full Site: text input
  return (
    <div style={{ paddingBottom: 16 }}>
      <Typography.Title level={4} style={{ marginBottom: 16 }}>
        Enter the domain to crawl
      </Typography.Title>

      <Form layout="vertical">
        <Form.Item
          label="Domain"
          validateStatus={domainError ? "error" : ""}
          help={domainError}
          required
        >
          <Input
            value={domain}
            onChange={(e) => onDomainChange(e.target.value)}
            placeholder="www.example.com"
            autoFocus
            prefix={
              domainError && (
                <Tooltip title={domainError}>
                  <ExclamationCircleOutlined style={{ color: "#ff4d4f", marginRight: 8 }} />
                </Tooltip>
              )
            }
          />
        </Form.Item>
      </Form>

      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        Enter the base domain (with or without https://). Examples:
        <ul style={{ marginTop: 8, marginBottom: 0 }}>
          <li>www.example.com</li>
          <li>example.com</li>
          <li>https://example.co.uk</li>
        </ul>
      </Typography.Paragraph>
    </div>
  );
}
