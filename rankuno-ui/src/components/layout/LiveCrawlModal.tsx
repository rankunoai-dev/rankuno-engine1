import {
  Alert,
  Form,
  Input,
  InputNumber,
  Modal,
  Switch,
  Typography,
} from "antd";
import { useState } from "react";
import { DEFAULT_CRAWL_REQUEST } from "../../adapters/adapterInterface";
import { useCrawlStore } from "../../store/useCrawlStore";
import type { PageClassificationInput } from "../../types/schema";

interface Props {
  open: boolean;
  onClose: () => void;
}

/** Form fields the operator controls. The rest of the payload uses defaults. */
interface FormValues {
  base_url: string;
  max_pages: number;
  max_depth: number | null;
  concurrency: number;
  crawl_dom: boolean;
  respect_robots: boolean;
}

/**
 * Start a live crawl against a URL the operator types.
 *
 * Deliberately not a bare "paste a URL" box. Each exposed field changes either
 * how long the crawl takes or how it behaves toward the target server, and an
 * operator who cannot see `respect_robots` cannot be held responsible for
 * having disabled it.
 */
export function LiveCrawlModal({ open, onClose }: Props): JSX.Element {
  const [form] = Form.useForm<FormValues>();
  const startCrawl = useCrawlStore((state) => state.startCrawl);
  const [submitting, setSubmitting] = useState(false);
  const [ignoreRobots, setIgnoreRobots] = useState(false);

  async function submit(): Promise<void> {
    const values = await form.validateFields();
    const request: PageClassificationInput = {
      ...DEFAULT_CRAWL_REQUEST,
      ...values,
      // An empty depth field means unlimited, not zero. AntD yields `null` for
      // a cleared InputNumber, which is already the value the API expects.
      max_depth: values.max_depth ?? null,
    };

    setSubmitting(true);
    onClose();
    try {
      // Awaited to completion — the store drives the whole polling lifecycle,
      // so closing the modal first leaves the progress visible in the header
      // rather than trapping the user behind a dialog for the whole crawl.
      await startCrawl(request);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      title="Start a live crawl"
      okText="Start crawl"
      confirmLoading={submitting}
      onOk={() => void submit()}
      onCancel={onClose}
      destroyOnClose
      width={520}
    >
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        initialValues={{
          base_url: "",
          max_pages: DEFAULT_CRAWL_REQUEST.max_pages,
          max_depth: null,
          concurrency: DEFAULT_CRAWL_REQUEST.concurrency,
          crawl_dom: true,
          respect_robots: true,
        }}
        onValuesChange={(changed: Partial<FormValues>) => {
          if (changed.respect_robots !== undefined) {
            setIgnoreRobots(!changed.respect_robots);
          }
        }}
      >
        <Form.Item
          name="base_url"
          label="Site root"
          rules={[
            { required: true, message: "Enter the site root to crawl." },
            { type: "url", message: "Must be a full URL, including https://" },
          ]}
        >
          <Input placeholder="https://www.example.com/" autoFocus />
        </Form.Item>

        <Form.Item
          name="max_pages"
          label="Page ceiling"
          extra="What actually bounds the crawl. 500 pages takes a couple of minutes; 20,000 takes hours at polite request rates."
          rules={[{ required: true, message: "A page ceiling is required." }]}
        >
          <InputNumber min={1} max={500_000} style={{ width: "100%" }} />
        </Form.Item>

        <Form.Item
          name="max_depth"
          label="Link depth ceiling"
          extra="Leave empty for unlimited. A depth limit does not reduce how many pages are fetched — the page budget is spent either way — it only decides whether deep pages are reachable."
        >
          <InputNumber min={0} max={15} placeholder="Unlimited" style={{ width: "100%" }} />
        </Form.Item>

        <Form.Item
          name="concurrency"
          label="Concurrency"
          extra="Local in-flight requests only. Per-host politeness is enforced by the fetcher regardless, so raising this cannot make the crawler rude to one site."
        >
          <InputNumber min={1} max={20} style={{ width: "100%" }} />
        </Form.Item>

        <Form.Item
          name="crawl_dom"
          label="Follow links (Path B)"
          valuePropName="checked"
          extra="Disabling is much cheaper but misses exactly the pages no sitemap lists."
        >
          <Switch />
        </Form.Item>

        <Form.Item name="respect_robots" label="Respect robots.txt" valuePropName="checked">
          <Switch />
        </Form.Item>

        {ignoreRobots && (
          <Alert
            type="error"
            showIcon
            message="Only disable this for a site you own."
            description="Ignoring robots.txt on someone else's server is a request they explicitly asked you not to make."
          />
        )}

        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          The engine reports no incremental page count, so the header shows an
          indeterminate indicator rather than a percentage while the crawl runs.
        </Typography.Paragraph>
      </Form>
    </Modal>
  );
}
