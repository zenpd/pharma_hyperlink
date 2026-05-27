/**
 * Screen 5 — Export & Submission Gate Center.
 *
 * 2×2 grid: format chooser, gate review workflow (spans 2 rows), compliance
 * posture, bundle preview. Print stylesheet still required for gate review
 * (`@media print` flattens chip colour to icon + text per the README).
 */

import React from "react";
import { CtdCrumb, DossierBar, Icon, TopBar } from "../components/shared";
import type { IconName } from "../components/shared";

type ApproverStatus = "signed" | "pending" | "blocked";
interface Approver {
  who: string;
  role: string;
  status: ApproverStatus;
  when: string;
  initials: string;
}

interface AuditRow {
  kind: "success" | "info" | "warning";
  who: string;
  what: string;
  when: string;
  hash: string;
  meta: string;
}

const APPROVERS: Approver[] = [
  { who: "V. Iyer", role: "QC Lead", status: "signed", when: "14:38", initials: "VI" },
  { who: "D. Park", role: "Author", status: "signed", when: "14:42", initials: "DP" },
  { who: "M. Tanaka", role: "Regulatory Affairs", status: "pending", when: "Required", initials: "MT" },
  { who: "S. Bhatt", role: "Submission Gate", status: "blocked", when: "Awaiting MT", initials: "SB" },
];

const AUDIT: AuditRow[] = [
  { kind: "success", who: "D. Park", what: "Signed as Author", when: "2026-05-26 14:42:08", hash: "0x7b29…", meta: "AKID: PIV-7421 · ECDSA-P256" },
  { kind: "success", who: "V. Iyer", what: "Signed as QC Lead", when: "2026-05-26 14:38:55", hash: "0xa3f1…", meta: "AKID: PIV-2918 · ECDSA-P256" },
  { kind: "info", who: "Engine", what: "Gate review submitted", when: "2026-05-26 14:36:02", hash: "0x91b4…", meta: "Bundle hash captured" },
  { kind: "info", who: "V. Iyer", what: "Resolved 4 blockers in m2.5.1", when: "2026-05-26 14:21:33", hash: "0x4e2d…", meta: "L-00214, L-00218, L-00301, L-00318" },
  { kind: "warning", who: "Engine", what: "34 anomalies flagged · m3.2.S", when: "2026-05-26 14:01:12", hash: "0x1c8a…", meta: "Style mutation cluster" },
];

export interface ExportGateProps {
  theme?: "light" | "dark";
}

export const ExportGate: React.FC<ExportGateProps> = ({ theme = "light" }) => (
  <div className={`hv-root ${theme === "dark" ? "theme-dark" : ""}`}>
    <TopBar theme={theme} activeTab="Reports" />
    <DossierBar
      right={
        <>
          <button className="btn btn-secondary btn-sm">
            <Icon name="history" size={12} /> Past exports
          </button>
          <button className="btn btn-secondary btn-sm" disabled style={{ opacity: 0.5 }}>
            <Icon name="lock" size={12} /> Seal sequence
          </button>
        </>
      }
    >
      <Icon name="package" size={15} color="var(--text-2)" />
      <span style={{ fontWeight: 600 }}>NDA 215842 · Brenzavir</span>
      <div className="divider-v" style={{ height: 16, margin: "0 4px" }} />
      <CtdCrumb parts={["Dossier"]} current="Export & Gate Center" />
    </DossierBar>

    <div
      style={{
        flex: 1,
        padding: 20,
        display: "grid",
        gridTemplateColumns: "1.1fr 1fr",
        gridTemplateRows: "auto 1fr",
        gap: 16,
        minHeight: 0,
      }}
    >
      {/* —— Format chooser —— */}
      <div className="card" style={{ padding: 16, gridColumn: "1", gridRow: "1" }}>
        <div style={{ display: "flex", alignItems: "center", marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>Export Bundle</div>
            <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 2 }}>
              Select formats for the submission package
            </div>
          </div>
          <span style={{ marginLeft: "auto" }} className="chip outline mono">
            3 / 3 selected
          </span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
          {(
            [
              { name: "CSV", desc: "Flat link inventory · all 2,147 rows", icon: "file-text" as IconName, size: "1.4 MB", selected: true, badge: undefined as string | undefined },
              { name: "XLSX", desc: "Conditional formatting by severity, sheet-per-module", icon: "file" as IconName, size: "4.8 MB", selected: true, badge: "recommended" },
              { name: "PDF", desc: "Management summary · readiness, KPIs, gate signatures", icon: "file-text" as IconName, size: "2.1 MB", selected: true, badge: undefined },
            ] as const
          ).map((f) => (
            <label
              key={f.name}
              style={{
                position: "relative",
                padding: 12,
                border: `1px solid ${f.selected ? "var(--brand)" : "var(--border)"}`,
                background: f.selected ? "var(--brand-tint)" : "var(--surface)",
                borderRadius: 4,
                cursor: "pointer",
                display: "flex",
                flexDirection: "column",
                gap: 6,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Icon
                  name={f.icon}
                  size={16}
                  color={f.selected ? "var(--brand-pressed)" : "var(--text-2)"}
                />
                <span
                  style={{
                    fontWeight: 600,
                    fontSize: 13,
                    color: f.selected ? "var(--brand-pressed)" : "var(--text-1)",
                  }}
                >
                  {f.name}
                </span>
                {f.badge && <span className="chip brand chip-sm">{f.badge}</span>}
                <div
                  style={{
                    marginLeft: "auto",
                    width: 16,
                    height: 16,
                    borderRadius: 3,
                    border: `1.5px solid ${f.selected ? "var(--brand)" : "var(--border-strong)"}`,
                    background: f.selected ? "var(--brand)" : "transparent",
                    display: "grid",
                    placeItems: "center",
                  }}
                >
                  {f.selected && <Icon name="check" size={10} color="#fff" strokeWidth={3} />}
                </div>
              </div>
              <div style={{ fontSize: 11, color: "var(--text-2)" }}>{f.desc}</div>
              <div
                className="mono"
                style={{ fontSize: 10, color: "var(--text-3)", marginTop: "auto" }}
              >
                {f.size} · est.
              </div>
            </label>
          ))}
        </div>
        <div
          style={{
            marginTop: 12,
            paddingTop: 12,
            borderTop: "1px solid var(--border)",
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 12,
            fontSize: 12,
          }}
        >
          <div>
            <div
              style={{
                color: "var(--text-3)",
                fontSize: 10,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                marginBottom: 4,
              }}
            >
              Scope
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span className="mono">Sequence 0009 · all modules</span>
              <Icon name="chevron-down" size={11} color="var(--text-3)" />
            </div>
          </div>
          <div>
            <div
              style={{
                color: "var(--text-3)",
                fontSize: 10,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                marginBottom: 4,
              }}
            >
              Include
            </div>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              <span className="chip">Valid</span>
              <span className="chip warning chip-sm">Warn</span>
              <span className="chip danger chip-sm">Blocker</span>
            </div>
          </div>
          <div>
            <div
              style={{
                color: "var(--text-3)",
                fontSize: 10,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                marginBottom: 4,
              }}
            >
              Sign with
            </div>
            <span className="mono" style={{ fontSize: 11 }}>
              PIV smartcard · ECDSA-P256
            </span>
          </div>
        </div>
      </div>

      {/* —— Gate review workflow (spans rows) —— */}
      <div
        className="card"
        style={{
          padding: 16,
          gridColumn: "2",
          gridRow: "1 / span 2",
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>Gate Review Workflow</div>
            <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 2 }}>
              Submission approval chain · 21 CFR Part 11 compliant
            </div>
          </div>
          <span style={{ marginLeft: "auto" }} className="chip warning">
            <Icon name="clock" size={10} /> 2 / 4 signed
          </span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 0, position: "relative" }}>
          {APPROVERS.map((a, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "10px 0",
                position: "relative",
              }}
            >
              {i < APPROVERS.length - 1 && (
                <div
                  style={{
                    position: "absolute",
                    left: 15,
                    top: 38,
                    width: 2,
                    height: "calc(100% - 28px)",
                    background: a.status === "signed" ? "var(--success)" : "var(--border)",
                  }}
                />
              )}
              <div
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: "50%",
                  display: "grid",
                  placeItems: "center",
                  background:
                    a.status === "signed"
                      ? "var(--success-tint)"
                      : a.status === "pending"
                      ? "var(--warning-tint)"
                      : "var(--neutral-tint)",
                  color:
                    a.status === "signed"
                      ? "var(--success)"
                      : a.status === "pending"
                      ? "var(--warning)"
                      : "var(--text-3)",
                  fontSize: 11,
                  fontWeight: 600,
                  border: a.status === "pending" ? "2px solid var(--warning)" : "none",
                  flexShrink: 0,
                  zIndex: 1,
                }}
              >
                {a.status === "signed" ? (
                  <Icon name="check" size={14} color="currentColor" strokeWidth={3} />
                ) : (
                  a.initials
                )}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{a.who}</div>
                <div style={{ fontSize: 11, color: "var(--text-2)" }}>{a.role}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div
                  style={{
                    fontSize: 11,
                    color:
                      a.status === "signed" ? "var(--success-text)" : "var(--text-2)",
                    fontWeight: 500,
                  }}
                >
                  {a.status === "signed"
                    ? "Signed"
                    : a.status === "pending"
                    ? "Pending"
                    : "Blocked"}
                </div>
                <div className="mono" style={{ fontSize: 10, color: "var(--text-3)" }}>
                  {a.when}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Audit trail */}
        <div style={{ marginTop: 16, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
          <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
            <span
              style={{
                fontSize: 11,
                color: "var(--text-3)",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
              }}
            >
              Audit Trail
            </span>
            <span className="chip outline chip-sm mono" style={{ marginLeft: "auto" }}>
              append-only · hashed
            </span>
          </div>
          <div
            style={{
              flex: 1,
              overflow: "hidden",
              display: "flex",
              flexDirection: "column",
              gap: 0,
            }}
          >
            {AUDIT.map((a, i) => {
              const tint =
                a.kind === "success"
                  ? "var(--success-tint)"
                  : a.kind === "info"
                  ? "var(--info-tint)"
                  : "var(--warning-tint)";
              const color =
                a.kind === "success"
                  ? "var(--success)"
                  : a.kind === "info"
                  ? "var(--info)"
                  : "var(--warning)";
              const iconName: IconName =
                a.kind === "success" ? "check" : a.kind === "warning" ? "alert" : "info";
              return (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    gap: 10,
                    padding: "10px 0",
                    borderBottom:
                      i < AUDIT.length - 1 ? "1px solid var(--border)" : "none",
                  }}
                >
                  <div
                    style={{
                      width: 20,
                      height: 20,
                      borderRadius: 4,
                      flexShrink: 0,
                      display: "grid",
                      placeItems: "center",
                      background: tint,
                      color,
                    }}
                  >
                    <Icon name={iconName} size={11} color="currentColor" strokeWidth={2.5} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12 }}>
                      <span style={{ fontWeight: 500 }}>{a.who}</span>
                      <span style={{ color: "var(--text-2)" }}> · {a.what}</span>
                    </div>
                    <div
                      className="mono"
                      style={{ fontSize: 10, color: "var(--text-3)", marginTop: 2 }}
                    >
                      {a.when} · hash {a.hash}
                    </div>
                    <div style={{ fontSize: 10, color: "var(--text-3)", marginTop: 1 }}>
                      {a.meta}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* —— Bundle summary + compliance + CTA —— */}
      <div
        style={{
          gridColumn: "1",
          gridRow: "2",
          display: "flex",
          flexDirection: "column",
          gap: 12,
          minHeight: 0,
        }}
      >
        <div className="card" style={{ padding: 14 }}>
          <div
            style={{
              fontSize: 11,
              color: "var(--text-3)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              marginBottom: 10,
            }}
          >
            Compliance Posture
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8 }}>
            {(
              [
                { icon: "shield-check" as IconName, title: "21 CFR Part 11", desc: "Audit-logged · electronic signatures" },
                { icon: "cpu" as IconName, title: "On-prem inference", desc: "No external data transmission" },
                { icon: "file-text" as IconName, title: "PDF/A-2b validated", desc: "Long-term archival format" },
                { icon: "lock" as IconName, title: "GxP environment", desc: "SunPharma VPC · isolated" },
              ] as const
            ).map((b) => (
              <div
                key={b.title}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 8,
                  padding: 10,
                  border: "1px solid var(--success-tint)",
                  background: "var(--success-tint)",
                  borderRadius: 4,
                }}
              >
                <Icon name={b.icon} size={14} color="var(--success)" strokeWidth={2} />
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: "var(--success-text)" }}>
                    {b.title}
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      color: "var(--success-text)",
                      opacity: 0.85,
                      marginTop: 2,
                    }}
                  >
                    {b.desc}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div
          className="card"
          style={{
            padding: 16,
            flex: 1,
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "center" }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600 }}>Bundle Preview</div>
              <div
                className="mono"
                style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2 }}
              >
                brenzavir-NDA-215842-seq-0009.zip
              </div>
            </div>
            <div style={{ marginLeft: "auto", textAlign: "right" }}>
              <div className="mono num" style={{ fontSize: 18, fontWeight: 600 }}>
                8.3 MB
              </div>
              <div className="mono" style={{ fontSize: 10, color: "var(--text-3)" }}>
                SHA-256: 0xc4f8…2e91
              </div>
            </div>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: 8,
              fontSize: 11,
            }}
          >
            {[
              { lbl: "Links exported", val: "2,147" },
              { lbl: "Docs covered", val: "500" },
              { lbl: "Sequence", val: "0009" },
            ].map((x) => (
              <div
                key={x.lbl}
                style={{ padding: 8, background: "var(--surface-raised)", borderRadius: 4 }}
              >
                <div
                  style={{
                    color: "var(--text-3)",
                    fontSize: 10,
                    textTransform: "uppercase",
                    letterSpacing: "0.06em",
                  }}
                >
                  {x.lbl}
                </div>
                <div
                  className="mono num"
                  style={{ fontSize: 16, fontWeight: 600, marginTop: 2 }}
                >
                  {x.val}
                </div>
              </div>
            ))}
          </div>

          <div
            style={{
              marginTop: "auto",
              padding: "10px 12px",
              border: "1px solid var(--warning-tint)",
              background: "var(--warning-tint)",
              borderRadius: 4,
              fontSize: 11,
              color: "var(--warning-text)",
              display: "flex",
              gap: 8,
              alignItems: "flex-start",
            }}
          >
            <Icon name="alert" size={12} color="var(--warning)" strokeWidth={2} />
            <div>
              <strong style={{ display: "block", marginBottom: 2 }}>
                13 blockers remain unresolved.
              </strong>
              Exporting will tag the bundle as <span className="mono">DRAFT</span> and require an
              additional Regulatory Affairs override.
            </div>
          </div>

          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-secondary">Preview management PDF</button>
            <button
              className="btn btn-primary"
              style={{ marginLeft: "auto", height: 36, padding: "0 16px" }}
            >
              <Icon name="download" size={14} color="#fff" /> Export bundle
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
);
