import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Alert, Empty, Typography } from "antd";
import { useMemo } from "react";
import { LEVEL_COLORS, LEVEL_LABELS, PAGE_TYPE_COLORS } from "../../constants/colors";
import { useCrawlStore } from "../../store/useCrawlStore";
import type { FullPageIntelligenceProfile, HierarchyLevel } from "../../types/schema";

/**
 * Nodes rendered before falling back to aggregation.
 *
 * React Flow renders real DOM elements per node. Past roughly this many the
 * frame rate collapses, so the graph shows the structurally important pages and
 * says so, rather than attempting 20,000 and freezing. The tree pane remains
 * the exhaustive view.
 */
const MAX_RENDERED_NODES = 300;

const LANES: HierarchyLevel[] = [
  "L0_HOMEPAGE",
  "L1_PRIMARY_NAV_HUB",
  "L2_SUB_NAV_HUB",
  "L3_LEAF_PAGE",
  "UTILITY_PAGE",
];

const LANE_X = 300;
const NODE_Y = 92;

interface CardData extends Record<string, unknown> {
  profile: FullPageIntelligenceProfile;
}

function LevelCard({ data }: NodeProps): JSX.Element {
  const { profile } = data as CardData;
  const accent = LEVEL_COLORS[profile.hierarchy_level];
  const typeColor = PAGE_TYPE_COLORS[profile.primary_page_type];
  const lowConfidence = profile.final_confidence_score < 0.85;

  return (
    <div
      style={{
        width: 230,
        borderRadius: 10,
        border: `1px solid ${accent}55`,
        borderLeft: `3px solid ${accent}`,
        background: "#131823",
        padding: "8px 10px",
        boxShadow: `0 0 14px ${accent}18`,
      }}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4 }}>
        <span
          style={{
            fontSize: 9,
            fontWeight: 700,
            color: accent,
            border: `1px solid ${accent}66`,
            borderRadius: 4,
            padding: "0 4px",
          }}
        >
          {LEVEL_LABELS[profile.hierarchy_level]}
        </span>
        <span style={{ fontSize: 9, color: typeColor }}>{profile.primary_page_type}</span>
      </div>

      <div
        style={{
          fontSize: 11,
          color: "#e2e8f0",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
        title={profile.url}
      >
        {shortPath(profile.normalized_path)}
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 5, fontSize: 10, color: "#64748b" }}>
        <span style={{ color: lowConfidence ? "#f59e0b" : "#10b981" }}>
          {(profile.final_confidence_score * 100).toFixed(0)}%
        </span>
        <span>in {profile.inbound_internal_links_count}</span>
        {profile.inbound_internal_links_count === 0 && (
          <span style={{ color: "#f87171" }}>orphan</span>
        )}
      </div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}

const NODE_TYPES = { levelCard: LevelCard };

/**
 * Right pane: pages arranged into hierarchy-level swimlanes.
 *
 * A deliberate difference from the left pane, worth understanding before it
 * reads as a bug: the tree nests by **URL path**, this graph groups by
 * **`hierarchy_level`**. Those are different axes by design (ADR 0002) — an L1
 * hub can live at any path depth — so a node's lane will not always match its
 * position in the tree. The banner says so on screen rather than leaving users
 * to work it out.
 */
export function ReactFlowGraph(): JSX.Element {
  const result = useCrawlStore((state) => state.result);
  const selectNode = useCrawlStore((state) => state.selectNode);
  const selectedUrl = useCrawlStore((state) => state.selectedUrl);

  const { nodes, edges, omitted } = useMemo(() => {
    if (!result) return { nodes: [], edges: [], omitted: 0 };
    return buildGraph(result.pages, selectedUrl);
  }, [result, selectedUrl]);

  if (!result) return <Empty description="No crawl loaded" style={{ marginTop: 120 }} />;

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "8px 12px", borderBottom: "1px solid #1e293b" }}>
        <Alert
          type="info"
          showIcon
          banner
          message={
            <Typography.Text style={{ fontSize: 12 }}>
              Lanes group by <strong>hierarchy level</strong>; the tree nests by{" "}
              <strong>URL path</strong>. A level is a page&apos;s role, not its position —
              so the two views intentionally differ.
              {omitted > 0 && (
                <>
                  {" "}
                  Showing the {MAX_RENDERED_NODES} most-linked pages;{" "}
                  <strong>{omitted.toLocaleString()} omitted</strong> — use the tree for
                  the full set.
                </>
              )}
            </Typography.Text>
          }
        />
      </div>

      <div style={{ flex: 1, minHeight: 0 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          fitView
          minZoom={0.05}
          proOptions={{ hideAttribution: true }}
          onNodeClick={(_event, node) => {
            const data = node.data as CardData;
            selectNode(data.profile.url);
          }}
        >
          <Background color="#1e293b" gap={22} />
          <Controls showInteractive={false} />
          <MiniMap
            pannable
            zoomable
            style={{ background: "#0a0d14" }}
            nodeColor={(node) =>
              LEVEL_COLORS[(node.data as CardData).profile.hierarchy_level]
            }
          />
        </ReactFlow>
      </div>
    </div>
  );
}

function buildGraph(
  pages: readonly FullPageIntelligenceProfile[],
  selectedUrl: string | null,
): { nodes: Node[]; edges: Edge[]; omitted: number } {
  // Rank by inbound links: when the budget forces a choice, the structurally
  // important pages are the ones worth drawing. Truncating in crawl order would
  // show an arbitrary slice.
  const ranked = [...pages].sort(
    (a, b) => b.inbound_internal_links_count - a.inbound_internal_links_count,
  );
  const visible = ranked.slice(0, MAX_RENDERED_NODES);
  const omitted = Math.max(0, pages.length - visible.length);

  const byLane = new Map<HierarchyLevel, FullPageIntelligenceProfile[]>();
  for (const lane of LANES) byLane.set(lane, []);
  for (const page of visible) byLane.get(page.hierarchy_level)?.push(page);

  const nodes: Node[] = [];
  const positions = new Map<string, string>();

  LANES.forEach((lane, laneIndex) => {
    const members = byLane.get(lane) ?? [];
    members.forEach((profile, row) => {
      const id = profile.url;
      positions.set(profile.normalized_path, id);
      nodes.push({
        id,
        type: "levelCard",
        position: { x: laneIndex * LANE_X, y: row * NODE_Y },
        data: { profile } satisfies CardData,
        selected: profile.url === selectedUrl,
      });
    });
  });

  // Edges follow URL-path parentage, the only containment the engine actually
  // produces: `nav_parent_url` is declared on the model but never populated.
  const edges: Edge[] = [];
  for (const profile of visible) {
    const parentPath = parentOf(profile.normalized_path);
    if (!parentPath) continue;
    const source = positions.get(parentPath);
    if (!source || source === profile.url) continue;
    edges.push({
      id: `${source}->${profile.url}`,
      source,
      target: profile.url,
      style: { stroke: "#1e293b", strokeWidth: 1 },
    });
  }

  return { nodes, edges, omitted };
}

function parentOf(normalizedPath: string): string | null {
  const trimmed = normalizedPath.endsWith("/")
    ? normalizedPath.slice(0, -1)
    : normalizedPath;
  const cut = trimmed.lastIndexOf("/");
  if (cut <= "https://".length) return null;
  return `${trimmed.slice(0, cut)}/`;
}

function shortPath(normalizedPath: string): string {
  const withoutScheme = normalizedPath.includes("://")
    ? normalizedPath.slice(normalizedPath.indexOf("://") + 3)
    : normalizedPath;
  const slash = withoutScheme.indexOf("/");
  const path = slash === -1 ? "/" : withoutScheme.slice(slash);
  return path.length > 34 ? `…${path.slice(-33)}` : path;
}
