/**
 * NewCrawlWizard: 4-Stage Wizard Container.
 *
 * Orchestrates the complete crawl form flow:
 * Stage 1: Source Selection
 * Stage 2: Domain Selection
 * Stage 3: Configuration
 * Stage 4: Advanced Options
 */

import { Button, Modal, Progress, Space, Steps, message } from "antd";
import { useEffect, useState } from "react";
import { useCrawlWizard } from "../../hooks/useCrawlWizard";
import { useCrawlStore } from "../../store/useCrawlStore";
import { SourceStage } from "./SourceStage";
import { DomainStage } from "./DomainStage";
import { ConfigStage } from "./ConfigStage";
import { AdvancedStage } from "./AdvancedStage";
import { validateDomain } from "../../lib/validation";

interface Props {
  open: boolean;
  onClose: () => void;
}

/**
 * NewCrawlWizard: Full 4-stage crawl form wizard.
 */
export function NewCrawlWizard({ open, onClose }: Props): JSX.Element {
  const {
    currentStage,
    formData,
    goToStage,
    nextStage,
    prevStage,
    updateFormData,
    reset,
    serializeToPayload,
  } = useCrawlWizard();

  const startCrawl = useCrawlStore((state) => state.startCrawl);
  const adapter = useCrawlStore((state) => state.adapter);
  const [submitting, setSubmitting] = useState(false);
  const [gscAccounts, setGscAccounts] = useState<string[]>([]);
  const [gscAccountsLoading, setGscAccountsLoading] = useState(false);

  // Fetch GSC accounts on open
  useEffect(() => {
    if (!open) return;
    const list = adapter?.listGscAccounts;
    if (!list) {
      setGscAccounts([]);
      return;
    }
    let cancelled = false;
    setGscAccountsLoading(true);
    list
      .call(adapter)
      .then((names) => {
        if (!cancelled) setGscAccounts(names);
      })
      .catch(() => {
        if (!cancelled) setGscAccounts([]);
      })
      .finally(() => {
        if (!cancelled) setGscAccountsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, adapter]);

  /**
   * Validate current stage and move to next if valid.
   */
  const handleNext = (): void => {
    const errors: string[] = [];

    if (currentStage === 1) {
      if (formData.source === "url_list" && formData.uploadedUrls.length === 0) {
        errors.push("Please upload a URL list file");
      }
    } else if (currentStage === 2) {
      const domainError = validateDomain(formData.domain);
      if (domainError) errors.push(domainError);
    } else if (currentStage === 3) {
      // Config stage validation is handled by individual components
    }

    if (errors.length > 0) {
      message.error(errors.join("; "));
      return;
    }

    nextStage();
  };

  /**
   * Submit the form and start crawl.
   */
  const handleSubmit = async (): Promise<void> => {
    // Final validation
    const domainError = validateDomain(formData.domain);
    if (domainError) {
      message.error(domainError);
      return;
    }

    setSubmitting(true);
    onClose();
    try {
      const payload = serializeToPayload();
      await startCrawl(payload);
      reset();
    } catch (err) {
      message.error(
        err instanceof Error ? err.message : "Failed to start crawl",
      );
      setSubmitting(false);
    }
  };

  const stageLabels = ["Source", "Domain", "Config", "Advanced"];

  return (
    <Modal
      open={open}
      onCancel={() => {
        if (!submitting) {
          onClose();
          reset();
        }
      }}
      width={600}
      title="New Crawl"
      footer={null}
      destroyOnClose
    >
      <div style={{ paddingBottom: 16 }}>
        {/* Stage indicator */}
        <Steps
          current={currentStage - 1}
          items={stageLabels.map((label) => ({ title: label }))}
          style={{ marginBottom: 24 }}
        />

        {/* Progress bar */}
        <Progress percent={Math.round((currentStage / 4) * 100)} showInfo={false} style={{ marginBottom: 24 }} />

        {/* Stage content */}
        <div style={{ minHeight: 300, marginBottom: 24 }}>
          {currentStage === 1 && (
            <SourceStage
              source={formData.source}
              uploadedUrls={formData.uploadedUrls}
              onSourceChange={(source) => updateFormData({ source, uploadedUrls: [] })}
              onUrlsChange={(urls) => updateFormData({ uploadedUrls: urls })}
            />
          )}

          {currentStage === 2 && (
            <DomainStage
              source={formData.source}
              domain={formData.domain}
              uploadedUrls={formData.uploadedUrls}
              onDomainChange={(domain) => updateFormData({ domain })}
            />
          )}

          {currentStage === 3 && (
            <ConfigStage
              configPreset={formData.configPreset}
              customRate={formData.customRate}
              customConcurrency={formData.customConcurrency}
              maxPages={formData.maxPages}
              onPresetChange={(preset) => updateFormData({ configPreset: preset })}
              onCustomRateChange={(rate) => updateFormData({ customRate: rate ?? undefined })}
              onCustomConcurrencyChange={(concurrency) =>
                updateFormData({ customConcurrency: concurrency ?? undefined })
              }
            />
          )}

          {currentStage === 4 && (
            <AdvancedStage
              proxy={formData.proxy}
              useAuth={!!formData.auth}
              authUsername={formData.auth?.username}
              authPassword={formData.auth?.password}
              customHeaders={formData.customHeaders}
              userAgent={formData.userAgent}
              verifySsl={formData.verifySsl}
              gscProperty={formData.gscProperty}
              ga4PropertyId={formData.ga4PropertyId}
              gscAccounts={gscAccounts}
              gscAccountsLoading={gscAccountsLoading}
              onProxyChange={(proxy) => updateFormData({ proxy })}
              onAuthToggle={(enabled) => {
                if (enabled && !formData.auth) {
                  updateFormData({ auth: { username: "", password: "" } });
                } else if (!enabled) {
                  updateFormData({ auth: null });
                }
              }}
              onAuthChange={(auth) => updateFormData({ auth })}
              onHeadersChange={(headers) => updateFormData({ customHeaders: headers ?? undefined })}
              onUserAgentChange={(ua) => updateFormData({ userAgent: ua })}
              onSSLToggle={(enabled) => updateFormData({ verifySsl: enabled })}
              onGscPropertyChange={(property) => updateFormData({ gscProperty: property })}
              onGA4PropertyChange={(id) => updateFormData({ ga4PropertyId: id })}
            />
          )}
        </div>

        {/* Action buttons */}
        <Space style={{ width: "100%", justifyContent: "flex-end" }}>
          <Button onClick={onClose} disabled={submitting}>
            Cancel
          </Button>

          {currentStage > 1 && (
            <Button onClick={prevStage} disabled={submitting}>
              Back
            </Button>
          )}

          {currentStage < 4 ? (
            <Button type="primary" onClick={handleNext} loading={submitting}>
              Next
            </Button>
          ) : (
            <Button type="primary" onClick={() => void handleSubmit()} loading={submitting}>
              Start Crawl
            </Button>
          )}
        </Space>
      </div>
    </Modal>
  );
}
