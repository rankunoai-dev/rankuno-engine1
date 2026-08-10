import {
  ApartmentOutlined,
  DownOutlined,
  MinusSquareOutlined,
} from "@ant-design/icons";
import { Button, Empty, Input, Select, Space, Tag, Tree, Typography } from "antd";
import type { DataNode } from "antd/es/tree";
import { useDeferredValue, useMemo, useState } from "react";
import { LEVEL_COLORS, LEVEL_LABELS, PAGE_TYPE_COLORS } from "../../constants/colors";
import { matchingPaths, pathsToDepth, presentPageTypes, type TreeNode } from "../../lib/tree";
import { useCrawlStore } from "../../store/useCrawlStore";

const { DirectoryTree } = Tree;

/** Rendered tree height. AntD only virtualizes when given an explicit height. */
const TREE_HEIGHT = 620;

/**
 * Left pane: a virtualized directory tree over the crawl.
 *
 * Two things make this survive 20,000 nodes:
 *
 * 1. `height` on the tree. Without it AntD renders every node to the DOM and the
 *    tab freezes — the failure is total, not gradual.
 * 2. `useDeferredValue` on the query. Filtering 20,000 nodes on every keystroke
 *    blocks input; deferring keeps typing responsive and lets React abandon
 *    superseded filter passes.
 */
export function DirectoryPane(): JSX.Element {
  const tree = useCrawlStore((state) => state.tree);
  const result = useCrawlStore((state) => state.result);
  const query = useCrawlStore((state) => state.query);
  const setQuery = useCrawlStore((state) => state.setQuery);
  const typeFilter = useCrawlStore((state) => state.typeFilter);
  const setTypeFilter = useCrawlStore((state) => state.setTypeFilter);
  const searchIndex = useCrawlStore((state) => state.searchIndex);
  const selectNode = useCrawlStore((state) => state.selectNode);

  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);
  const deferredQuery = useDeferredValue(query);

  const matched = useMemo(
    () => matchingPaths(searchIndex, deferredQuery),
    [searchIndex, deferredQuery],
  );

  const typeOptions = useMemo(
    () => (result ? presentPageTypes(result.pages) : []),
    [result],
  );

  const data = useMemo(() => {
    if (!tree) return [];
    const allowed = new Set(typeFilter);
    return tree.children.map((child) =>
      toDataNode(child, matched, deferredQuery.length > 0, allowed),
    );
  }, [tree, matched, deferredQuery, typeFilter]);

  // A search should reveal its hits. Collapsed matches deep in the tree read as
  // "no results", which is the most common way tree search feels broken.
  const effectiveExpanded = useMemo(
    () => (deferredQuery.length > 0 ? [...matched] : expandedKeys),
    [deferredQuery, matched, expandedKeys],
  );

  if (!tree) {
    return <Empty description="No crawl loaded" style={{ marginTop: 80 }} />;
  }

  const expandTo = (depth: number): void => setExpandedKeys(pathsToDepth(tree, depth));

  return (
    <div style={{ padding: 12, display: "flex", flexDirection: "column", gap: 10 }}>
      <Input.Search
        placeholder="Filter by path or page type…"
        allowClear
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />

      <Space size={4} wrap>
        <Button size="small" icon={<ApartmentOutlined />} onClick={() => expandTo(1)}>
          L1
        </Button>
        <Button size="small" icon={<ApartmentOutlined />} onClick={() => expandTo(2)}>
          L2
        </Button>
        <Button size="small" icon={<DownOutlined />} onClick={() => expandTo(99)}>
          All
        </Button>
        <Button
          size="small"
          icon={<MinusSquareOutlined />}
          onClick={() => setExpandedKeys([])}
        >
          Collapse
        </Button>
      </Space>

      <Select
        mode="multiple"
        allowClear
        size="small"
        placeholder="Filter by page type"
        value={typeFilter}
        onChange={setTypeFilter}
        options={typeOptions.map((type) => ({ label: type, value: type }))}
        maxTagCount={2}
      />

      {deferredQuery.length > 0 && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {matched.size === 0
            ? "No matches"
            : `${matched.size.toLocaleString()} nodes matched`}
        </Typography.Text>
      )}

      <DirectoryTree
        treeData={data}
        height={TREE_HEIGHT}
        virtual
        showIcon={false}
        selectable
        expandedKeys={effectiveExpanded}
        onExpand={(keys) => setExpandedKeys(keys as string[])}
        onSelect={(_keys, info) => {
          const url = (info.node as DataNode & { url?: string }).url;
          if (url) selectNode(url);
        }}
      />
    </div>
  );
}

/**
 * Convert a tree node into AntD's shape.
 *
 * A filtered-out node keeps its children when a descendant matches — otherwise
 * filtering by a leaf's page type would hide the path to it and the result
 * would look empty.
 */
function toDataNode(
  node: TreeNode,
  matched: Set<string>,
  searching: boolean,
  allowedTypes: Set<string>,
): DataNode & { url?: string } {
  const children = node.children
    .map((child) => toDataNode(child, matched, searching, allowedTypes))
    .filter((child) => child !== null);

  const typeAllowed =
    allowedTypes.size === 0 ||
    (node.profile !== null && allowedTypes.has(node.profile.primary_page_type));
  const searchAllowed = !searching || matched.has(node.path);
  const dimmed = !(typeAllowed && searchAllowed) && children.length > 0;

  return {
    key: node.path,
    url: node.profile?.url,
    isLeaf: node.children.length === 0,
    children: children.length > 0 ? children : undefined,
    title: <NodeTitle node={node} dimmed={dimmed} />,
  };
}

function NodeTitle({ node, dimmed }: { node: TreeNode; dimmed: boolean }): JSX.Element {
  const profile = node.profile;
  const level = profile?.hierarchy_level;

  return (
    <span style={{ opacity: dimmed ? 0.35 : 1, whiteSpace: "nowrap" }}>
      {level && (
        <Tag
          color={LEVEL_COLORS[level]}
          style={{ marginInlineEnd: 6, fontSize: 10, lineHeight: "16px", padding: "0 5px" }}
        >
          {LEVEL_LABELS[level]}
        </Tag>
      )}
      <span style={{ fontWeight: node.children.length > 0 ? 550 : 400 }}>
        /{node.segment}
      </span>
      {profile && (
        <Tag
          bordered={false}
          style={{
            marginInlineStart: 6,
            fontSize: 10,
            lineHeight: "16px",
            padding: "0 5px",
            background: `${PAGE_TYPE_COLORS[profile.primary_page_type]}22`,
            color: PAGE_TYPE_COLORS[profile.primary_page_type],
          }}
        >
          {profile.primary_page_type}
        </Tag>
      )}
      {node.descendantCount > 0 && (
        <Typography.Text type="secondary" style={{ fontSize: 11, marginInlineStart: 6 }}>
          {node.descendantCount.toLocaleString()}
        </Typography.Text>
      )}
      {/* A structural node the crawl never returned. Marked so a gap in the
          tree reads as a gap, not as a page that exists but was misclassified. */}
      {!profile && (
        <Typography.Text type="secondary" style={{ fontSize: 11, marginInlineStart: 6 }}>
          not crawled
        </Typography.Text>
      )}
    </span>
  );
}
