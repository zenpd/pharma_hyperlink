/**
 * DocViewer — standalone, deep-linked document viewer opened in a NEW TAB
 * (PLAN TWELVE, Word path / Option B).
 *
 * Browsers can't render a .docx inline, so a Word target in the Linked Documents
 * pane can't be opened the way PDFs are. Instead the pane opens THIS viewer in a
 * new tab: it renders the target document with the same block model as the
 * compare panes (paragraphs + real tables) and auto-scrolls to / highlights the
 * referenced section or table — the Word equivalent of the PDF "#page=N" scroll.
 *
 * Booted from the URL hash (`#/docview?run=&doc=&ref=`) in App.tsx, so no router
 * is required and the new tab is a normal deep-link into the SPA bundle. The
 * fetch carries the session cookie, so the PLAN SEVEN classification gate still
 * applies (a blocked document shows an access message).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { DocPreview, DocPreviewBlock } from "../types";
import { findRefBlockIndex } from "../refMatch";

interface Props {
  runId: string;
  doc: string;
  refText?: string;
}

const niceDocName = (s: string) =>
  (s.split(/[\\/]/).pop() ?? s).replace(/_linked\.(docx|pdf)$/i, "");

/** Locate the block that defines / contains the reference. Shares the compare
 *  view's type-aware, boundary-safe matcher so a Section/Appendix reference
 *  never lands on a table, and "2.5" never matches inside "14.2.5.1". */
function findRefIndex(blocks: DocPreviewBlock[], ref?: string): number {
  return findRefBlockIndex(blocks, ref);
}

export function DocViewer({ runId, doc, refText }: Props) {
  const [preview, setPreview] = useState<DocPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const blockRefs = useRef<Record<number, HTMLElement | null>>({});
  const [flashIndex, setFlashIndex] = useState<number | null>(null);

  useEffect(() => {
    document.title = `${niceDocName(doc)} — Document Viewer`;
    let cancelled = false;
    api.pipeline
      .documentPreview(runId, doc)
      .then((p) => { if (!cancelled) setPreview(p); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); });
    return () => { cancelled = true; };
  }, [runId, doc]);

  const targetIndex = useMemo(
    () => (preview ? findRefIndex(preview.paragraphs, refText) : -1),
    [preview, refText],
  );

  useEffect(() => {
    if (targetIndex < 0) return;
    // Small delay so the DOM has painted after the preview state update.
    const tid = window.setTimeout(() => {
      blockRefs.current[targetIndex]?.scrollIntoView({ behavior: "smooth", block: "center" });
      setFlashIndex(targetIndex);
      window.setTimeout(() => setFlashIndex(null), 2600);
    }, 200);
    return () => window.clearTimeout(tid);
  }, [targetIndex]);

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "0 20px 60px", color: "#1a1a1a" }}>
      <div
        style={{
          position: "sticky", top: 0, zIndex: 5, background: "#fff",
          borderBottom: "1px solid #e5e7eb", padding: "14px 0", marginBottom: 16,
        }}
      >
        <div style={{ fontWeight: 700, fontSize: 16 }}>📄 {niceDocName(doc)}</div>
        {refText && (
          <div style={{ fontSize: 12, color: "#555", marginTop: 2 }}>
            Referenced: <strong>{refText}</strong>
            {preview && targetIndex < 0 && (
              <span style={{ color: "#b45309" }}>
                {" "}— not located in this document; showing from the top.
              </span>
            )}
          </div>
        )}
      </div>

      {error && (
        <div style={{ padding: 16, color: "#b71c1c", fontSize: 14 }}>
          {/403|classified|forbidden/i.test(error)
            ? "🔒 You don't have access to this document."
            : `Could not load the document: ${error}`}
        </div>
      )}
      {!error && !preview && <div style={{ padding: 16, color: "#888" }}>Loading…</div>}

      {preview &&
        preview.paragraphs.map((b) => {
          const setRef = (el: HTMLElement | null) => { blockRefs.current[b.index] = el; };
          const flashStyle = {
            transition: "background 0.4s",
            background: flashIndex === b.index ? "#fff3bf" : "transparent",
            borderRadius: 4,
          } as const;

          if (b.type === "image" && b.src) {
            return (
              <div key={b.index} ref={setRef} style={{ margin: "10px 0", padding: 2, ...flashStyle }}>
                <img src={b.src} alt="figure"
                  style={{ display: "block", maxWidth: "100%", height: "auto", border: "1px solid #eee", borderRadius: 4 }} />
              </div>
            );
          }
          if (b.type === "table" && b.rows && b.rows.length) {
            return (
              <div key={b.index} ref={setRef} style={{ margin: "10px 0", padding: 2, ...flashStyle }}>
                <table style={{ borderCollapse: "collapse", fontSize: 12, width: "100%" }}>
                  <tbody>
                    {b.rows.map((row, ri) => (
                      <tr key={ri}>
                        {row.map((cell, ci) => (
                          <td
                            key={ci}
                            style={{ border: "1px solid #d0d0d0", padding: "3px 6px", verticalAlign: "top" }}
                          >
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          }
          return (
            <p
              key={b.index}
              ref={setRef}
              style={{ margin: "6px 0", padding: "1px 3px", fontSize: 14, lineHeight: 1.5, ...flashStyle }}
            >
              {b.text}
            </p>
          );
        })}
    </div>
  );
}
