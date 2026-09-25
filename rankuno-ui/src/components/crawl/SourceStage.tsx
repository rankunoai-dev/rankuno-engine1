/**
 * Stage 1: Source Selection (Full Site vs URL List).
 *
 * Allows the user to choose between crawling a full domain or uploading a URL list.
 * For URL lists, handles file upload with CSV/TXT parsing.
 */

import { Button, Divider, Empty, Progress, Radio, Space, Typography, Upload, message } from "antd";
import { useCallback, useState } from "react";
import type { UploadFile } from "antd";
import type { CrawlSource } from "../../types/crawlWizard";
import { parseUploadedFile } from "../../lib/urlParser";

interface Props {
  source: CrawlSource;
  uploadedUrls: string[];
  onSourceChange: (source: CrawlSource) => void;
  onUrlsChange: (urls: string[]) => void;
}

/**
 * Stage 1: Source Selection.
 *
 * Two options: Full Site (crawl entire domain) or URL List (upload file with URLs).
 */
export function SourceStage({ source, uploadedUrls, onSourceChange, onUrlsChange }: Props): JSX.Element {
  const [uploading, setUploading] = useState(false);
  const [fileList, setFileList] = useState<UploadFile[]>([]);

  /**
   * Handle file upload: read file and parse URLs.
   */
  const handleUpload = useCallback(
    async (file: UploadFile) => {
      setUploading(true);
      try {
        const reader = new FileReader();
        reader.onload = (e) => {
          const contents = e.target?.result as string;
          if (!contents) {
            message.error("Failed to read file");
            setUploading(false);
            return;
          }

          try {
            const urls = parseUploadedFile(file.originFileObj as File, contents);
            if (urls.length === 0) {
              message.warning("No valid URLs found in file");
              setUploading(false);
              return;
            }

            onUrlsChange(urls);
            setFileList([file]);
            message.success(`Parsed ${urls.length} URLs from file`);
          } catch (err) {
            message.error(`Failed to parse file: ${err instanceof Error ? err.message : "Unknown error"}`);
          } finally {
            setUploading(false);
          }
        };

        reader.onerror = () => {
          message.error("Failed to read file");
          setUploading(false);
        };

        reader.readAsText(file.originFileObj as File);
      } catch (err) {
        message.error(`Upload failed: ${err instanceof Error ? err.message : "Unknown error"}`);
        setUploading(false);
      }
    },
    [onUrlsChange],
  );

  return (
    <div style={{ paddingBottom: 16 }}>
      <Typography.Title level={4} style={{ marginBottom: 24 }}>
        How do you want to crawl?
      </Typography.Title>

      <Radio.Group value={source} onChange={(e) => onSourceChange(e.target.value)}>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Radio value="full_site">
            <div>
              <div style={{ fontWeight: 500 }}>Full Site Crawl</div>
              <div style={{ fontSize: 12, color: "#666", marginTop: 4 }}>
                Crawl an entire domain starting from the root URL
              </div>
            </div>
          </Radio>

          <Radio value="url_list">
            <div>
              <div style={{ fontWeight: 500 }}>URL List Upload</div>
              <div style={{ fontSize: 12, color: "#666", marginTop: 4 }}>
                Upload a CSV or text file with specific URLs to crawl
              </div>
            </div>
          </Radio>
        </Space>
      </Radio.Group>

      {source === "url_list" && (
        <>
          <Divider />

          <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
            Upload a CSV or TXT file with one URL per line. The file will be parsed to extract unique domains.
          </Typography.Paragraph>

          <Upload.Dragger
            multiple={false}
            maxCount={1}
            accept=".csv,.txt"
            loading={uploading}
            beforeUpload={(file) => {
              const isCSVOrTXT = file.type === "text/csv" || file.type === "text/plain" ||
                                 file.name.endsWith(".csv") ||
                                 file.name.endsWith(".txt");
              if (!isCSVOrTXT) {
                message.error("Please upload a CSV or TXT file");
              }
              return isCSVOrTXT || Upload.LIST_IGNORE;
            }}
            customRequest={async (options) => {
              const file = options.file as UploadFile;
              await handleUpload(file);
              options.onSuccess?.({}, new XMLHttpRequest());
            }}
            style={{ marginBottom: 16 }}
          >
            <div style={{ padding: "32px 0" }}>
              <p style={{ fontSize: 16, fontWeight: 500 }}>
                Click to select or drag CSV/TXT file
              </p>
              <p style={{ fontSize: 12, color: "#999" }}>
                CSV and text files with one URL per line (or column)
              </p>
            </div>
          </Upload.Dragger>

          {uploadedUrls.length > 0 && (
            <>
              <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 8 }}>
                <strong>{uploadedUrls.length}</strong> URLs parsed from file
              </Typography.Paragraph>
              <Progress percent={100} status="success" style={{ marginBottom: 16 }} />

              <div style={{ marginTop: 16, padding: 12, background: "#f5f5f5", borderRadius: 4 }}>
                <Typography.Paragraph style={{ fontSize: 12, margin: 0, marginBottom: 8 }}>
                  <strong>Sample URLs:</strong>
                </Typography.Paragraph>
                <div
                  style={{
                    maxHeight: 120,
                    overflowY: "auto",
                    fontSize: 12,
                    fontFamily: "monospace",
                  }}
                >
                  {uploadedUrls.slice(0, 5).map((url, idx) => (
                    <div key={idx} style={{ color: "#666", marginBottom: 4 }}>
                      {url}
                    </div>
                  ))}
                  {uploadedUrls.length > 5 && (
                    <div style={{ color: "#999", fontSize: 11 }}>
                      ... and {uploadedUrls.length - 5} more
                    </div>
                  )}
                </div>
              </div>
            </>
          )}

          {fileList.length > 0 && (
            <Button
              type="text"
              size="small"
              danger
              onClick={() => {
                setFileList([]);
                onUrlsChange([]);
              }}
              style={{ marginTop: 8 }}
            >
              Clear file
            </Button>
          )}
        </>
      )}

      {source === "full_site" && (
        <div style={{ marginTop: 16, padding: 12, background: "#fafafa", borderRadius: 4 }}>
          <Typography.Paragraph
            type="secondary"
            style={{ fontSize: 12, margin: 0 }}
          >
            You'll enter the site root URL (e.g., https://www.example.com) in the next step.
          </Typography.Paragraph>
        </div>
      )}
    </div>
  );
}
