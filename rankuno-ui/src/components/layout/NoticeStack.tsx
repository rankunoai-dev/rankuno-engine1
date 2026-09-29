import { EyeInvisibleOutlined } from "@ant-design/icons";
import { Alert, Button } from "antd";
import type { DashboardNotice } from "../../lib/dashboardNotices";
import { useNoticeStore } from "../../store/useNoticeStore";

interface NoticeStackProps {
  /** Every banner that applies to the loaded crawl, in display order. */
  notices: DashboardNotice[];
  /**
   * The crawl these banners describe, or `null` when no job is selected.
   *
   * `null` makes the stack read-only. A dismissal has to be recorded against
   * something, and recording it against "no crawl" is the global dismissal
   * this feature is specifically not allowed to have.
   */
  crawlId: string | null;
}

/**
 * The dashboard's stacked safety banners, with a way to put them away.
 *
 * Dismissal is per crawl and per banner, and the count of what is hidden stays
 * on screen with a control that brings it back. That combination is the whole
 * design: the banner comment in `DashboardShell` warns that truncation,
 * synthetic data, a zero-fetch crawl and a blocked crawl are each a way to read
 * the screen confidently and wrongly, and each cost a cycle to make visible. A
 * close button that made a finding unrecoverable, or that carried to the next
 * crawl, would undo that work. One that leaves "3 hidden notices" in the same
 * place the banners were does not — the finding is one click away and the fact
 * that there is a finding never leaves the screen.
 */
export function NoticeStack({ notices, crawlId }: NoticeStackProps): JSX.Element | null {
  const dismissedIds = useNoticeStore((state) => (crawlId ? state.dismissed[crawlId] : undefined));
  const dismiss = useNoticeStore((state) => state.dismiss);
  const restoreAll = useNoticeStore((state) => state.restoreAll);

  const hidden = new Set(dismissedIds ?? []);
  // Filtered against what is *firing now*, so a dismissal left over from a
  // banner that no longer applies cannot inflate the hidden count into a
  // control that restores nothing.
  const visible = notices.filter((notice) => !hidden.has(notice.id));
  const hiddenCount = notices.length - visible.length;

  if (notices.length === 0) return null;

  return (
    <>
      {visible.map((notice) => (
        <Alert
          key={notice.id}
          type={notice.type}
          banner
          showIcon
          message={notice.message}
          /* `closeIcon: true` is load-bearing, not decoration: antd only
             treats an object `closable` as closable when it carries one, so
             an object with the label alone renders no close button at all.
             `true` selects antd's own `CloseOutlined`, which is what every
             other closable surface in the app shows. */
          closable={
            crawlId === null
              ? false
              : { closeIcon: true, "aria-label": `Dismiss the ${notice.label} notice` }
          }
          onClose={() => {
            if (crawlId) dismiss(crawlId, notice.id);
          }}
        />
      ))}

      {hiddenCount > 0 && crawlId !== null && (
        <div className="rk-notice-restore">
          <Button
            type="link"
            size="small"
            icon={<EyeInvisibleOutlined />}
            onClick={() => restoreAll(crawlId)}
          >
            {`${hiddenCount} hidden ${hiddenCount === 1 ? "notice" : "notices"} — show again`}
          </Button>
        </div>
      )}
    </>
  );
}
