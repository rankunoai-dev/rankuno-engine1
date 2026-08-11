import {
  Alert,
  Form,
  Input,
  InputNumber,
  Modal,
  Segmented,
  Switch,
  Typography,
} from "antd";
import { useState } from "react";
import { CRAWL_SPEEDS, DEFAULT_CRAWL_REQUEST } from "../../adapters/adapterInterface";
import { useCrawlStore } from "../../store/useCrawlStore";
import type { PageClassificationInput } from "../../types/schema";

interface Props {
  open: boolean;
  onClose: () => void;
}

/** Form fields the operator controls. The rest of the payload uses defaults. */
interface FormValues {
  base_url: string;
  max_pages: number | null;
  max_depth: number | null;
  speed: "polite" | "standard" | "turbo";
  crawl_dom: boolean;
  respect_robots: boolean;
  browser_headers: boolean;
  user_agent: string;
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
  const [browserMode, setBrowserMode] = useState(false);
  const [speed, setSpeed] = useState<"polite" | "standard" | "turbo">("polite");

  async function submit(): Promise<void> {
    const values = await form.validateFields();
    const preset = CRAWL_SPEEDS.find((option) => option.key === values.speed) ?? CRAWL_SPEEDS[0]!;
    const { speed: _speed, ...rest } = values;

    const request: PageClassificationInput = {
      ...DEFAULT_CRAWL_REQUEST,
      ...rest,
      rate_limit_rps: preset.rate_limit_rps,
      concurrency: preset.concurrency,
      // Empty means no ceiling — every reachable page, up to the engine's own
      // 500,000 limit. `null` is what the API expects; `undefined` would fall
      // back to the model default of 20,000 and quietly cap the crawl.
      max_pages: values.max_pages ?? null,
      // An empty depth field means unlimited, not zero. AntD yields `null` for
      // a cleared InputNumber, which is already the value the API expects.
      max_depth: values.max_depth ?? null,
      // An empty field means "whatever browser mode implies"; the engine only
      // substitutes its browser token while this holds the default.
      user_agent: values.user_agent?.trim() || DEFAULT_CRAWL_REQUEST.user_agent,
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
          speed: "polite",
          crawl_dom: true,
          respect_robots: true,
          browser_headers: false,
          user_agent: DEFAULT_CRAWL_REQUEST.user_agent,
        }}
        onValuesChange={(changed: Partial<FormValues>) => {
          if (changed.respect_robots !== undefined) {
            setIgnoreRobots(!changed.respect_robots);
          }
          if (changed.speed !== undefined) setSpeed(changed.speed);
          if (changed.browser_headers !== undefined) {
            setBrowserMode(changed.browser_headers);
            // The engine substitutes a browser token only while the field still
            // holds the default. Showing that substitution here keeps the form
            // honest about what will actually be sent.
            if (changed.browser_headers && form.getFieldValue("user_agent") === DEFAULT_CRAWL_REQUEST.user_agent) {
              form.setFieldValue("user_agent", "");
            } else if (!changed.browser_headers && !form.getFieldValue("user_agent")) {
              form.setFieldValue("user_agent", DEFAULT_CRAWL_REQUEST.user_agent);
            }
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
          extra="Leave empty to crawl every reachable page, up to the engine's 500,000 limit. Not truly unbounded: the crawl holds every page in memory, so a site larger than that would exhaust it rather than finish."
        >
          <InputNumber
            min={1}
            max={500_000}
            placeholder="Every reachable page"
            style={{ width: "100%" }}
          />
        </Form.Item>

        <Form.Item name="speed" label="Crawl speed">
          <Segmented
            block
            options={CRAWL_SPEEDS.map((option) => ({
              label: option.label,
              value: option.key,
            }))}
          />
        </Form.Item>

        <Typography.Paragraph type="secondary" style={{ fontSize: 11, marginTop: -12 }}>
          {CRAWL_SPEEDS.find((option) => option.key === speed)?.detail}
          {". "}
          A declared Crawl-delay always wins: a site asking to be crawled slowly
          is never sped up by this setting.
        </Typography.Paragraph>

        {speed === "turbo" && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="25 requests per second is real load on the target server."
            description="Appropriate for a site you own or have written permission to crawl at this rate. On anything else, Standard or Polite is the right choice."
          />
        )}

        <Form.Item
          name="max_depth"
          label="Link depth ceiling"
          extra="Leave empty for unlimited. A depth limit does not reduce how many pages are fetched — the page budget is spent either way — it only decides whether deep pages are reachable."
        >
          <InputNumber min={0} max={15} placeholder="Unlimited" style={{ width: "100%" }} />
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

        <Form.Item
          name="browser_headers"
          label="Present as a browser"
          valuePropName="checked"
          extra="Sends a desktop Chrome user agent and the Accept headers a browser sends. Some enterprise edges refuse any client they do not recognise — returning 403 even for robots.txt, so the site cannot state what it permits. Use on sites you own or have permission to crawl. robots.txt is still obeyed, matched against whatever token is sent."
        >
          <Switch />
        </Form.Item>

        <Form.Item
          name="user_agent"
          label="User agent"
          extra={
            browserMode
              ? "Leave empty to send the desktop Chrome token. A value here overrides it."
              : "The token sent and matched against robots.txt. A descriptive token with contact details is what lets a site owner allow or block you deliberately."
          }
        >
          <Input placeholder={browserMode ? "Chrome (default for browser mode)" : "RankunoBot"} />
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
