import { useCallback, useEffect, useRef, useState } from "react";

const MIN_LEFT = 280;
const MIN_RIGHT = 360;
const DEFAULT_LEFT = 420;

/**
 * Resizable two-pane container.
 *
 * Hand-rolled rather than pulling a split-pane dependency: the behaviour is a
 * pointer listener and a width, and a library would add a bundle for something
 * the whole component expresses in forty lines.
 *
 * Dragging writes to a ref and only commits to state on pointer-up, so a drag
 * does not re-render a 20,000-node tree on every mouse move.
 */
export function SplitPaneLayout({
  left,
  right,
}: {
  left: React.ReactNode;
  right: React.ReactNode;
}): JSX.Element {
  const [leftWidth, setLeftWidth] = useState(DEFAULT_LEFT);
  const containerRef = useRef<HTMLDivElement>(null);
  const leftRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const pending = useRef(DEFAULT_LEFT);

  const onPointerMove = useCallback((event: PointerEvent) => {
    if (!dragging.current || !containerRef.current || !leftRef.current) return;
    const bounds = containerRef.current.getBoundingClientRect();
    const next = Math.min(
      Math.max(event.clientX - bounds.left, MIN_LEFT),
      bounds.width - MIN_RIGHT,
    );
    pending.current = next;
    // Width applied directly during the drag; React state waits for release.
    leftRef.current.style.width = `${next}px`;
  }, []);

  const onPointerUp = useCallback(() => {
    if (!dragging.current) return;
    dragging.current = false;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    setLeftWidth(pending.current);
  }, []);

  useEffect(() => {
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    };
  }, [onPointerMove, onPointerUp]);

  return (
    <div ref={containerRef} style={{ display: "flex", flex: 1, minHeight: 0 }}>
      <div
        ref={leftRef}
        style={{
          width: leftWidth,
          flexShrink: 0,
          borderRight: "1px solid #1e293b",
          overflow: "auto",
        }}
      >
        {left}
      </div>

      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize panes"
        onPointerDown={() => {
          dragging.current = true;
          document.body.style.cursor = "col-resize";
          document.body.style.userSelect = "none";
        }}
        style={{
          width: 5,
          cursor: "col-resize",
          background: "#111827",
          flexShrink: 0,
        }}
      />

      <div style={{ flex: 1, minWidth: 0, minHeight: 0 }}>{right}</div>
    </div>
  );
}
