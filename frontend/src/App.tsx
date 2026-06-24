/**
 * App shell
 *
 * Sidebar navigation mapped to screens.  Visited screens stay mounted
 * (hidden via display:none) so state is preserved when you navigate
 * away and come back — no spinner on every back-navigation.
 *
 * Sidebar groups:
 *   AI Pipeline  → Run Pipeline, Run Compare, Review Queue, Compliance Gate
 *   Reports      → Overview, Module Matrix, Link Inspector, Issues, Export
 *   Analysis     → Comparison, Detection Trace
 */

import { useEffect, useState } from "react";
import { api } from "./api";
import { Dashboard } from "./screens/Dashboard";
import { Issues } from "./screens/Issues";
import { Comparison } from "./screens/Comparison";
import { DetectionTrace } from "./screens/DetectionTrace";
import { Pipeline } from "./screens/Pipeline";
import { ReviewQueue } from "./screens/ReviewQueue";
import { ComplianceGate } from "./screens/ComplianceGate";
import { ModuleMatrix } from "./screens/ModuleMatrix";
import { LinksTable } from "./screens/LinksTable";
import { ExportCenter } from "./screens/ExportCenter";
import { RunCompare } from "./screens/RunCompare";
import { ReferenceView } from "./screens/ReferenceView";
import type { RefTarget } from "./screens/ReferenceView";
import { ActiveRunProvider } from "./contexts/ActiveRun";
import { AuthProvider, useAuth } from "./contexts/Auth";
import { Login } from "./screens/Login";
import { RunSelector } from "./components/RunSelector";
import { DocViewer } from "./screens/DocViewer";
import type { Screen } from "./types";
import "./styles/app.css";

/** PLAN TWELVE (Word path): a `#/docview?run=&doc=&ref=` hash means this tab was
 *  opened from the Linked Documents pane to view one document — render the
 *  standalone viewer instead of the full app shell. */
function parseDocViewHash(): { run: string; doc: string; ref?: string } | null {
  const h = window.location.hash || "";
  const q = h.indexOf("?");
  if (!h.startsWith("#/docview") || q < 0) return null;
  const params = new URLSearchParams(h.slice(q + 1));
  const run = params.get("run");
  const doc = params.get("doc");
  if (!run || !doc) return null;
  return { run, doc, ref: params.get("ref") || undefined };
}

// Screens under Reports + Analysis that read run-scoped data and therefore
// show the Run Selector bar (pick a live run, or the demo seed).
const REPORT_SCREENS: Screen[] = [
  "dashboard", "module-matrix", "links-table", "issues", "export",
  "comparison", "detection-trace",
];

// ── Navigation definition ─────────────────────────────────────────────────────

interface NavItem { screen: Screen; label: string; }
interface NavGroup { label: string; items: NavItem[]; }

const NAV_GROUPS: NavGroup[] = [
  {
    label: "AI Pipeline",
    items: [
      { screen: "pipeline", label: "Run Pipeline" },
      { screen: "run-compare", label: "Run Compare" },
      { screen: "review", label: "Review Queue" },
      { screen: "compliance", label: "Compliance Gate" },
    ],
  },
  // ── Reports + Analysis groups ────────────────────────────────────────────
  // These screens now follow the run picked in the Run Selector bar (shown at
  // the top of each screen). They read run-scoped data from
  // /api/pipeline/run/{run_id}/{score|anomalies|links|detection-trace|export.*}
  // — i.e. the live pipeline run you just executed. When no completed run
  // exists (or you pick "Demo data"), they fall back to the seeded demo
  // dossier (/api/dossiers/demo/...) so the screens are never empty.
  {
    label: "Reports",
    items: [
      { screen: "dashboard", label: "Overview" },
      { screen: "module-matrix", label: "Module Matrix" },
      { screen: "links-table", label: "Link Inspector" },
      { screen: "issues", label: "Issues" },
      { screen: "export", label: "Export" },
    ],
  },
  {
    label: "Analysis",
    items: [
      { screen: "comparison", label: "Comparison" },
      { screen: "detection-trace", label: "Detection Trace" },
    ],
  },
];

// ── Security header controls (PLAN SEVEN Feature C) ─────────────────────────

function SecurityControls() {
  const { mode, user, logout, setSecurityEnabled } = useAuth();
  const [busy, setBusy] = useState(false);
  if (!mode) return null;

  const enabled = mode.enabled;
  const isAdmin = !!user?.is_admin;

  async function flip(next: boolean) {
    setBusy(true);
    try {
      await setSecurityEnabled(next);
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const chip: React.CSSProperties = {
    padding: "3px 10px",
    borderRadius: 12,
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: "0.03em",
    whiteSpace: "nowrap",
  };

  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
      {/* Gate status + toggle */}
      <span
        style={{
          ...chip,
          color: enabled ? "#14532d" : "#7c2d12",
          background: enabled ? "#dcfce7" : "#ffedd5",
        }}
        title={
          enabled
            ? "Authentication + classified-document gate is enforced"
            : "Security gate is OFF — all documents are visible without login"
        }
      >
        {enabled ? "🔐 Security ON" : "🔓 Security OFF"}
      </span>

      {/* Flip button: while ON only admins see it; while OFF anyone may
          re-arm it, but not when the backend lacks the SuperTokens SDK
          (the gate would fail closed and 503 every request). */}
      {(enabled ? isAdmin : mode.supertokens_available) && (
        <button
          className="btn-ghost btn-sm"
          disabled={busy}
          onClick={() => flip(!enabled)}
          style={{
            fontSize: 11, padding: "3px 10px", borderRadius: 6, cursor: "pointer",
            border: "1px solid rgba(255,255,255,0.25)",
            background: "transparent", color: "#e8e8e8",
          }}
          title={enabled ? "Disable the security gate (audit-logged)" : "Enable the security gate (audit-logged)"}
        >
          {busy ? "…" : enabled ? "Disable" : "Enable"}
        </button>
      )}

      {/* Logged-in identity + sign-out (only meaningful while the gate is on) */}
      {enabled && user && (
        <>
          <span style={{ fontSize: 12, color: "rgba(255,255,255,0.75)" }}>
            {user.email || user.user_id}
            {user.is_admin && (
              <span style={{ ...chip, marginLeft: 6, color: "#1e3a8a", background: "#dbeafe" }}>
                ADMIN
              </span>
            )}
          </span>
          <button
            onClick={() => logout()}
            style={{
              fontSize: 11, padding: "3px 10px", borderRadius: 6, cursor: "pointer",
              border: "1px solid rgba(255,255,255,0.25)",
              background: "transparent", color: "#e8e8e8",
            }}
            title="Sign out"
          >
            Sign out
          </button>
        </>
      )}

      <span className="on-prem-badge">On-Prem</span>
    </span>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  // A document-viewer deep-link (opened in a new tab from the Linked Documents
  // pane) renders the standalone viewer, bypassing the nav shell. The preview
  // fetch carries the session cookie, so the classification gate still applies.
  const docView = parseDocViewHash();
  if (docView) {
    return <DocViewer runId={docView.run} doc={docView.doc} refText={docView.ref} />;
  }
  return (
    <AuthProvider>
      <AppGate />
    </AuthProvider>
  );
}

/** Renders Login while the gate is on with no session; the shell otherwise. */
function AppGate() {
  const { loading, authRequired } = useAuth();
  if (loading) return null; // brief blank instead of a login flash
  if (authRequired) return <Login />;
  return <AppShell />;
}

function AppShell() {
  const { mode } = useAuth();
  // Default landing is the live Pipeline screen (legacy demo Overview hidden).
  const [screen, setScreen] = useState<Screen>("pipeline");
  const [navOpen, setNavOpen] = useState(true);

  // Track which screens have ever been visited so we can keep them mounted.
  // A screen is rendered once visited; hidden (display:none) when not active.
  // This preserves component state (form inputs, loaded data, scroll position)
  // when the user navigates away and returns.
  const [visited, setVisited] = useState<Set<Screen>>(new Set(["pipeline"]));

  // Pending review count — drives the red badge on the Review Queue nav item.
  const [reviewCount, setReviewCount] = useState(0);

  // Cross-screen navigation state
  const [complianceRunId, setComplianceRunId] = useState<string | undefined>();
  const [compareTarget, setCompareTarget] = useState<{ runId?: string; doc?: string }>({});
  // Reference View target (set when a hyperlink is clicked in Run Compare).
  const [refRunId, setRefRunId] = useState<string | undefined>();
  const [refTarget, setRefTarget] = useState<RefTarget | undefined>();

  function navigate(s: Screen) {
    setVisited((prev) => new Set([...prev, s]));
    setScreen(s);
  }

  // Refresh the pending-review count on load and on every screen change, so
  // the badge updates right after a run is sent to (or cleared from) review.
  useEffect(() => {
    api.review.queue()
      .then((data) => {
        const pending = (data.runs ?? []).filter((r) => r.review_status === "pending_review").length;
        setReviewCount(pending);
      })
      .catch(() => { /* badge is best-effort */ });
  }, [screen]);

  function goToCompliance(runId: string) {
    setComplianceRunId(runId);
    navigate("compliance");
  }

  function goToRunCompare(runId: string, doc?: string) {
    setCompareTarget({ runId, doc });
    navigate("run-compare");
  }

  function goToReference(runId: string, target: RefTarget) {
    setRefRunId(runId);
    setRefTarget(target);
    navigate("reference-view");
  }

  const allItems = NAV_GROUPS.flatMap((g) => g.items);
  const active = allItems.find((i) => i.screen === screen);

  // Helper: render a screen only if visited; hide when not active
  function slot(s: Screen, node: React.ReactNode) {
    if (!visited.has(s)) return null;
    return (
      <div key={s} style={{ display: screen === s ? undefined : "none" }}>
        {node}
      </div>
    );
  }

  return (
    <ActiveRunProvider>
      <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>

        {/* ── Header ── */}
        <header className="app-header" style={{ flexShrink: 0 }}>
          <button
            onClick={() => setNavOpen((o) => !o)}
            style={{
              background: "none", border: "none", cursor: "pointer",
              color: "#e8e8e8", fontSize: 18, padding: "0 4px", marginRight: 4,
            }}
            title="Toggle sidebar"
          >
            ☰
          </button>

          <span
            className="logo"
            style={{ cursor: "pointer" }}
            onClick={() => navigate("pipeline")}
          >
            Hyperlink Engine
          </span>

          {active && (
            <span style={{ marginLeft: 12, fontSize: 13, color: "rgba(255,255,255,0.5)" }}>
              / {active.label}
            </span>
          )}

          {/* <SecurityControls /> */}
          <span className="on-prem-badge">On-Prem</span>
        </header>

        {/* Warning banner: an admin explicitly switched the gate OFF */}
        {/* {mode && !mode.enabled && mode.source === "override" && (
          <div
            style={{
              flexShrink: 0,
              padding: "6px 16px",
              fontSize: 12,
              fontWeight: 600,
              color: "#7c2d12",
              background: "#fff7ed",
              borderBottom: "1px solid #fed7aa",
            }}
          >
            ⚠ Security gate is OFF — every document (including classified) is
            visible without login. This change was made by an admin and is
            audit-logged.
          </div>
        )} */}

        <div style={{ display: "flex", flex: 1, minHeight: 0 }}>

          {/* ── Sidebar ── */}
          {navOpen && (
            <nav style={{
              width: 190, flexShrink: 0,
              background: "var(--surface)",
              borderRight: "1px solid var(--border)",
              overflowY: "auto",
              padding: "12px 0",
            }}>
              {NAV_GROUPS.map((grp) => (
                <div key={grp.label} style={{ marginBottom: 8 }}>
                  <div style={{
                    padding: "6px 16px 4px",
                    fontSize: 10, fontWeight: 700,
                    textTransform: "uppercase", letterSpacing: "0.08em",
                    color: "var(--text-muted)",
                  }}>
                    {grp.label}
                  </div>
                  {grp.items.map((item) => {
                    const isActive = screen === item.screen;
                    return (
                      <button
                        key={item.screen}
                        onClick={() => navigate(item.screen)}
                        style={{
                          display: "flex", alignItems: "center",
                          width: "100%", padding: "8px 16px",
                          border: "none", cursor: "pointer", textAlign: "left",
                          fontSize: 13,
                          fontWeight: isActive ? 600 : 400,
                          background: isActive ? "rgba(59,130,246,0.08)" : "transparent",
                          color: isActive ? "var(--primary)" : "var(--text)",
                          borderLeft: isActive ? "3px solid var(--primary)" : "3px solid transparent",
                          transition: "all 0.1s",
                        }}
                      >
                        <span style={{ flex: 1 }}>{item.label}</span>
                        {item.screen === "review" && reviewCount > 0 && (
                          <span style={{
                            background: "var(--danger, #dc2626)", color: "#fff",
                            borderRadius: 10, fontSize: 10, fontWeight: 700,
                            minWidth: 18, height: 18, padding: "0 5px",
                            display: "inline-flex", alignItems: "center", justifyContent: "center",
                          }}>
                            {reviewCount}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              ))}

              {/* <div style={{
              margin: "12px 16px 0",
              paddingTop: 12,
              borderTop: "1px solid var(--border)",
              fontSize: 10, color: "var(--text-muted)", lineHeight: 1.6,
            }}>
              No data leaves this machine.
            </div> */}
            </nav>
          )}

          {/* ── Main content ── */}
          <main style={{ flex: 1, overflowY: "auto", minWidth: 0 }}>

            {/* Run Selector — lets Reports/Analysis follow a live run or demo seed */}
            {REPORT_SCREENS.includes(screen) && (
              <div style={{ padding: "12px 24px 0" }}>
                <RunSelector />
              </div>
            )}

            {slot("dashboard", (
              <Dashboard
                onViewIssues={() => navigate("issues")}
                onViewComparison={() => navigate("comparison")}
                onViewDetectionTrace={() => navigate("detection-trace")}
                onViewPipeline={() => navigate("pipeline")}
              />
            ))}

            {slot("pipeline", (
              <Pipeline
                onBack={() => navigate("dashboard")}
                onGoToReview={() => navigate("review")}
                onCompareDoc={goToRunCompare}
              />
            ))}

            {slot("run-compare", (
              <RunCompare
                onBack={() => navigate("pipeline")}
                active={screen === "run-compare"}
                initialRunId={compareTarget.runId}
                initialDoc={compareTarget.doc}
                onOpenReference={goToReference}
              />
            ))}

            {slot("reference-view", (
              <ReferenceView
                onBack={() => navigate("run-compare")}
                active={screen === "reference-view"}
                runId={refRunId}
                target={refTarget}
              />
            ))}

            {slot("review", (
              <ReviewQueue
                onBack={() => navigate("dashboard")}
                onGoToCompliance={goToCompliance}
              />
            ))}

            {slot("compliance", (
              <ComplianceGate
                onBack={() => navigate("dashboard")}
                preselectedRunId={complianceRunId}
              />
            ))}

            {slot("module-matrix", (
              <ModuleMatrix onBack={() => navigate("dashboard")} />
            ))}

            {slot("links-table", (
              <LinksTable onBack={() => navigate("dashboard")} />
            ))}

            {slot("export", (
              <ExportCenter onBack={() => navigate("dashboard")} />
            ))}

            {slot("issues", (
              <Issues onBack={() => navigate("dashboard")} />
            ))}

            {slot("comparison", (
              <Comparison onBack={() => navigate("dashboard")} />
            ))}

            {slot("detection-trace", (
              <DetectionTrace onBack={() => navigate("dashboard")} />
            ))}

          </main>
        </div>
      </div>
    </ActiveRunProvider>
  );
}
