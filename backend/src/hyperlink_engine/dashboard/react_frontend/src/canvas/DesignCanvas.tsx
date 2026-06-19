/**
 * DesignCanvas — production-friendly variant of the mockup's design canvas.
 *
 * The original handoff used a draggable, zoomable canvas as the design-time
 * surface. In production we want a navigable app with one screen per route;
 * but during the design-review phase it's useful to see all 6 artboards on
 * a single page (scaled down) the way the original entry HTML rendered them.
 *
 * This component is a lightweight "all-screens-at-once" wall — fixed-size
 * frames laid out in a grid. It's the production analogue of the
 * mockup_source/design-canvas.jsx wrapper.
 */

import React from "react";

export interface ArtboardSpec {
  id: string;
  label: string;
  /** Fully rendered screen component instance (already themed). */
  node: React.ReactNode;
}

export interface DesignCanvasProps {
  artboards: ArtboardSpec[];
  /** Scale factor applied to each 1440×900 artboard (0.5 = half size). */
  scale?: number;
}

const ART_W = 1440;
const ART_H = 900;

export const DesignCanvas: React.FC<DesignCanvasProps> = ({ artboards, scale = 0.55 }) => (
  <div
    style={{
      minHeight: "100vh",
      background: "#f0eee9",
      padding: 32,
      fontFamily: "'Inter', system-ui, sans-serif",
      color: "rgba(40,30,20,0.85)",
    }}
  >
    <header style={{ marginBottom: 24 }}>
      <div
        style={{
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: "0.16em",
          color: "rgba(60,50,40,0.6)",
        }}
      >
        Design Canvas · {artboards.length} artboards
      </div>
      <h1
        style={{
          margin: "8px 0 0",
          fontFamily: "'Inter Tight', 'Inter', sans-serif",
          fontSize: 28,
          fontWeight: 600,
          letterSpacing: "-0.015em",
        }}
      >
        Hyperlink Engine — QC Dashboard
      </h1>
    </header>

    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(auto-fill, minmax(${ART_W * scale + 40}px, 1fr))`,
        gap: 40,
      }}
    >
      {artboards.map((a) => (
        <figure
          key={a.id}
          style={{
            margin: 0,
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          <figcaption
            style={{
              fontSize: 11,
              color: "rgba(60,50,40,0.7)",
              fontFamily:
                "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <span
              style={{
                fontFamily: "'JetBrains Mono', ui-monospace, monospace",
                fontSize: 10,
                color: "rgba(60,50,40,0.5)",
              }}
            >
              {a.id}
            </span>
            <span>· {a.label}</span>
          </figcaption>
          <div
            style={{
              width: ART_W * scale,
              height: ART_H * scale,
              overflow: "hidden",
              background: "var(--bg)",
              borderRadius: 6,
              boxShadow:
                "0 12px 40px rgba(0,0,0,0.10), 0 2px 4px rgba(0,0,0,0.06)",
              position: "relative",
            }}
          >
            <div
              style={{
                width: ART_W,
                height: ART_H,
                transform: `scale(${scale})`,
                transformOrigin: "top left",
              }}
            >
              {a.node}
            </div>
          </div>
        </figure>
      ))}
    </div>
  </div>
);
