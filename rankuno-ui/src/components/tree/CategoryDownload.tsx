import { DownloadOutlined } from "@ant-design/icons";
import { categoryCsv, categoryFilename } from "../../lib/categoryCsv";
import type { DashModel, DashNode } from "../../lib/dashboardModel";
import { downloadCsv } from "../../lib/csv";

interface Props {
  model: DashModel;
  node: DashNode;
  /** Pixel offset of the row this control sits on, matching the row's `top`. */
  top: number;
}

/**
 * Width reserved on the right of a category row so its count and branch
 * control are not drawn under this button. Must match the button's width in
 * `.vspacer .tdl` (tree-overlay.css).
 */
export const CATEGORY_DOWNLOAD_GUTTER = 84;

/**
 * The per-category "download these URLs" control.
 *
 * A sibling of the row rather than a child: the row carries the `button` role,
 * and a `<button>` nested inside it is invalid, the same reason the branch
 * control is a `span`. Being a native `<button>` gives Enter and Space for free.
 *
 * The count shown is `node.cnt`, which the model accumulates as the number of
 * URL-bearing nodes in the subtree — the same set `categoryCsv` writes — so the
 * number on the control is the number of rows in the file.
 */
export function CategoryDownload({ model, node, top }: Props): JSX.Element {
  const count = node.cnt;
  const empty = count === 0;
  const label = `Download URLs for ${node.label}`;

  return (
    <button
      type="button"
      className="tdl"
      style={{ top: top + 3 }}
      aria-label={label}
      disabled={empty}
      title={
        empty
          ? `No URLs under ${node.label} to download`
          : `${label} (${count.toLocaleString()} URLs, CSV)`
      }
      onClick={() => downloadCsv(categoryFilename(node.label), categoryCsv(model, node.i))}
    >
      <span aria-hidden="true">
        <DownloadOutlined />
      </span>
      {empty ? "No URLs" : count.toLocaleString()}
    </button>
  );
}
