import { useState } from "react";
import { Dashboard } from "./screens/Dashboard";
import { Issues } from "./screens/Issues";
import { Comparison } from "./screens/Comparison";
import { DetectionTrace } from "./screens/DetectionTrace";
import type { Screen } from "./types";
import "./styles/app.css";

export default function App() {
  const [screen, setScreen] = useState<Screen>("dashboard");

  return (
    <>
      {/* ── Header ── */}
      <header className="app-header">
        <span
          className="logo"
          style={{ cursor: "pointer" }}
          onClick={() => setScreen("dashboard")}
        >
          🔗 Hyperlink Engine
        </span>
        <span className="version">QC Dashboard · v1.0</span>

        <span className="on-prem-badge">
          🔒 On-Prem Only
        </span>
      </header>

      {/* ── Screen Router ── */}
      {screen === "dashboard" && (
        <Dashboard
          onViewIssues={() => setScreen("issues")}
          onViewComparison={() => setScreen("comparison")}
          onViewDetectionTrace={() => setScreen("detection-trace")}
        />
      )}

      {screen === "issues" && (
        <Issues onBack={() => setScreen("dashboard")} />
      )}

      {screen === "comparison" && (
        <Comparison onBack={() => setScreen("dashboard")} />
      )}

      {screen === "detection-trace" && (
        <DetectionTrace onBack={() => setScreen("dashboard")} />
      )}
    </>
  );
}
