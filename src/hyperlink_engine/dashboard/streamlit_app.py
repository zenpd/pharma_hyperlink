"""W8.3 — Streamlit Dashboard v1 (Rapid POC).

Run with::

    poetry run streamlit run src/hyperlink_engine/dashboard/streamlit_app.py

The dashboard loads a previously-generated dossier report directory
(``output/bench/<timestamp>/``) and renders:

  1. Home page — overall readiness score (gauge chart)
  2. Per-module health matrix (heatmap-style table)
  3. Anomaly browser with severity / kind filters
  4. Link inspector (click module → docs → links)
  5. Export buttons (CSV / XLSX)

Because the engine is on-prem, the dashboard reads local files only — no
network calls.  Phase 3 will replace this with the React frontend.

Usage notes
-----------
* Launch without arguments — a file picker in the sidebar lets the operator
  choose the report root directory.
* Set ``HYPERLINK_STREAMLIT_REPORT_DIR`` env var to pre-select a directory.
* All computations are cached with ``@st.cache_data`` so re-renders are fast.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Streamlit is an optional dependency — import lazily so the rest of the
# engine can be imported without it installed.
try:
    import streamlit as st
    _ST_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ST_AVAILABLE = False


def _require_streamlit() -> None:  # pragma: no cover
    if not _ST_AVAILABLE:
        raise ImportError(
            "streamlit is required for the dashboard. "
            "Install it with: pip install streamlit"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Data loading helpers (cached per run directory)
# ─────────────────────────────────────────────────────────────────────────────


def _load_dossier_csv(report_root: Path) -> "pd.DataFrame":  # type: ignore[name-defined]
    import pandas as pd

    aggregate = report_root / "dossier_links.csv"
    if aggregate.exists():
        return pd.read_csv(aggregate, dtype=str).fillna("")
    # Fall back: concatenate per-doc CSVs
    frames = []
    for csv_path in sorted(report_root.rglob("*.csv")):
        if csv_path.name == "dossier_links.csv":
            continue
        try:
            frames.append(pd.read_csv(csv_path, dtype=str).fillna(""))
        except Exception:
            pass
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _status_counts(df: "pd.DataFrame") -> dict[str, int]:  # type: ignore[name-defined]
    if df.empty or "status" not in df.columns:
        return {}
    return df["status"].value_counts().to_dict()


# ─────────────────────────────────────────────────────────────────────────────
# Page renderers
# ─────────────────────────────────────────────────────────────────────────────


def _render_gauge(score: float) -> None:
    """Render a simple gauge using Plotly."""
    try:
        import plotly.graph_objects as go

        color = "#27AE60" if score >= 90 else "#E67E22" if score >= 70 else "#E74C3C"
        fig = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=score,
                domain={"x": [0, 1], "y": [0, 1]},
                title={"text": "Submission Readiness Score"},
                gauge={
                    "axis": {"range": [0, 100], "tickwidth": 1},
                    "bar": {"color": color},
                    "steps": [
                        {"range": [0, 55], "color": "#FADBD8"},
                        {"range": [55, 70], "color": "#FDEBD0"},
                        {"range": [70, 90], "color": "#FDFBEF"},
                        {"range": [90, 100], "color": "#EAFAF1"},
                    ],
                    "threshold": {
                        "line": {"color": "black", "width": 2},
                        "thickness": 0.75,
                        "value": 90,
                    },
                },
            )
        )
        fig.update_layout(height=300, margin=dict(t=40, b=0, l=20, r=20))
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.metric("Readiness Score", f"{score:.1f}/100")


def _render_home(df: "pd.DataFrame") -> None:  # type: ignore[name-defined]
    st.header("📋 Dossier Overview")

    if df.empty:
        st.warning("No link records found in the selected report directory.")
        return

    counts = _status_counts(df)
    total = len(df)
    broken = counts.get("broken", 0)
    ok = counts.get("ok", 0)
    suspicious = counts.get("suspicious", 0)
    unverified = counts.get("unverified", 0)

    broken_rate = broken / total * 100 if total else 0.0
    # Simple score: 100 - 5*broken_rate - 2*(suspicious+unverified)/total*100
    score = max(0.0, 100.0 - 5 * broken_rate - 2 * (suspicious + unverified) / max(total, 1) * 100)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Links", total)
    col2.metric("✅ OK", ok)
    col3.metric("❌ Broken", broken, delta=f"-{broken_rate:.1f}%", delta_color="inverse")
    col4.metric("⚠️ Suspicious", suspicious)
    col5.metric("❓ Unverified", unverified)

    st.divider()
    _render_gauge(score)

    grade = "A" if score >= 95 else "B" if score >= 85 else "C" if score >= 70 else "D" if score >= 55 else "F"
    ready_label = "✅ SUBMISSION READY" if score >= 90 and broken == 0 else "❌ NOT READY"
    st.info(f"**Grade {grade}** — {ready_label}")


def _render_module_matrix(df: "pd.DataFrame") -> None:  # type: ignore[name-defined]
    st.header("📦 Module Health Matrix")

    if df.empty or "source_doc" not in df.columns:
        st.info("No data available.")
        return

    import pandas as pd  # noqa: PLC0415

    # Derive module from source_doc path
    def _module_of(path: str) -> str:
        parts = Path(path).parts
        for part in parts:
            if part.startswith(("m1", "m2", "m3", "m4", "m5")):
                return part[:2]
        return "other"

    df = df.copy()
    df["module"] = df["source_doc"].apply(_module_of)

    grouped = (
        df.groupby(["module", "status"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )
    st.dataframe(grouped, use_container_width=True)


def _render_anomaly_browser(df: "pd.DataFrame") -> None:  # type: ignore[name-defined]
    st.header("🔍 Link Inspector")

    if df.empty:
        st.info("No link records.")
        return

    # Filters
    col1, col2 = st.columns(2)
    status_filter = col1.multiselect(
        "Status filter",
        options=["broken", "suspicious", "unverified", "ok"],
        default=["broken", "suspicious"],
    )
    doc_filter = col2.text_input("Filter by document name (substring)")

    filtered = df.copy()
    if status_filter and "status" in filtered.columns:
        filtered = filtered[filtered["status"].isin(status_filter)]
    if doc_filter and "source_doc" in filtered.columns:
        filtered = filtered[
            filtered["source_doc"].str.contains(doc_filter, case=False, na=False)
        ]

    st.caption(f"Showing {len(filtered):,} of {len(df):,} link records")
    st.dataframe(
        filtered[["source_doc", "link_text", "status", "target_anchor", "error_msg"]],
        use_container_width=True,
        height=400,
    )


def _render_export(df: "pd.DataFrame", report_root: Path) -> None:  # type: ignore[name-defined]
    st.header("⬇️ Export")

    col1, col2 = st.columns(2)

    # CSV export
    if not df.empty:
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        col1.download_button(
            label="Download CSV",
            data=csv_bytes,
            file_name="dossier_links_export.csv",
            mime="text/csv",
        )

    # XLSX export (requires openpyxl)
    try:
        import io

        import openpyxl

        buf = io.BytesIO()
        with openpyxl.Workbook() as wb:
            ws = wb.active
            ws.title = "Links"
            if not df.empty:
                ws.append(list(df.columns))
                for row in df.itertuples(index=False):
                    ws.append(list(row))
            wb.save(buf)
        buf.seek(0)
        col2.download_button(
            label="Download XLSX",
            data=buf.getvalue(),
            file_name="dossier_links_export.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except ImportError:
        col2.info("Install openpyxl for XLSX export: `pip install openpyxl`")


# ─────────────────────────────────────────────────────────────────────────────
# Main entrypoint
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Plan Two — Run Pipeline page
# ─────────────────────────────────────────────────────────────────────────────


def _render_run_pipeline() -> None:  # pragma: no cover
    """Upload dossier documents, trigger the pipeline, watch live state."""
    import tempfile

    st.header("🚀 Run Pipeline")
    st.caption(
        "Upload documents (`.docx` or `.pdf`), trigger the AI pipeline, "
        "and watch the orchestration state in real time."
    )

    # ── Step 1: Upload ─────────────────────────────────────────────────────
    st.subheader("1 · Upload Documents")
    dossier_id = st.text_input(
        "Dossier ID (optional)",
        value="",
        placeholder="e.g. DOS-2026-DEMO",
        help="Leave blank to auto-assign a run ID.",
    )
    uploaded_files = st.file_uploader(
        "Drop your dossier documents here",
        type=["docx", "pdf"],
        accept_multiple_files=True,
        help="Upload 1–10 Word or PDF documents. Cross-document references will be detected and linked.",
    )

    if not uploaded_files:
        st.info("Upload at least one `.docx` document to begin.")
        return

    st.success(f"✅ {len(uploaded_files)} file(s) ready: " + ", ".join(f.name for f in uploaded_files))

    # ── Step 2: Trigger ────────────────────────────────────────────────────
    st.subheader("2 · Run the Pipeline")
    col1, col2 = st.columns([1, 3])
    run_clicked = col1.button("▶  Run Now", type="primary", use_container_width=True)

    if not run_clicked:
        col2.caption(
            "The engine will: **ingest → parse → detect references "
            "(regex + NER + Ollama) → inject hyperlinks → validate → score**"
        )
        return

    # ── Save uploaded files to a temp dir ─────────────────────────────────
    with tempfile.TemporaryDirectory(prefix="hle_upload_") as tmpdir:
        tmp = Path(tmpdir)
        input_files = []
        for uf in uploaded_files:
            dest = tmp / uf.name
            dest.write_bytes(uf.read())
            input_files.append(dest)

        # ── Step 3: Live orchestration ──────────────────────────────────────
        st.subheader("3 · Live Pipeline State")
        _run_pipeline_with_live_state(input_files, dossier_id, tmp)


def _run_pipeline_with_live_state(
    input_files: list[Path],
    dossier_id: str,
    base_dir: Path,
) -> None:  # pragma: no cover
    """Run the pipeline synchronously, updating the Streamlit stepper live."""
    from hyperlink_engine.orchestration.runner import PipelineRunner
    from hyperlink_engine.orchestration.state import PipelineState, run_store
    from hyperlink_engine.orchestration.events import NODE_LABELS

    output_dir = base_dir / "output"
    output_dir.mkdir(exist_ok=True)

    state = PipelineState.new(input_files, output_dir, dossier_id)
    run_store.create(state)

    # Stepper: one row per node in the execution order
    node_order = [
        "load_dossier", "parse_all", "detect_references", "resolve_targets",
        "inject_links", "validate", "score_and_report",
    ]
    node_status: dict[str, str] = {n: "pending" for n in node_order}

    # Build stepper UI placeholders
    stepper_slots: dict[str, Any] = {}
    cols = st.columns(len(node_order))
    for i, node in enumerate(node_order):
        with cols[i]:
            stepper_slots[node] = st.empty()
            stepper_slots[node].markdown(f"⏸ **{NODE_LABELS.get(node, node)}**")

    st.divider()
    log_container = st.empty()
    log_lines: list[str] = []

    def _on_event(event: dict) -> None:
        node = event.get("node", "")
        status = event.get("status", "")
        if node in node_status:
            node_status[node] = status
            icon = "🟡" if status == "running" else "✅" if status == "done" else "❌"
            label = NODE_LABELS.get(node, node)
            stepper_slots[node].markdown(f"{icon} **{label}**")
        details = event.get("details") or {}
        detail_str = " · ".join(f"{k}={v}" for k, v in details.items() if v not in (None, "", {}))
        msg = f"`{node}` {status}" + (f" — {detail_str}" if detail_str else "")
        log_lines.append(msg)
        log_container.markdown("\n\n".join(f"• {l}" for l in log_lines[-12:]))

    runner = PipelineRunner()
    with st.spinner("Pipeline running…"):
        final_state = runner.invoke(state, on_event=_on_event)

    # ── Step 4: Results ─────────────────────────────────────────────────────
    st.subheader("4 · Results")

    score = final_state.get("score", 0.0)
    grade = final_state.get("grade", "F")
    total_links = len(final_state.get("links", []))
    broken = sum(1 for l in final_state.get("links", []) if l.get("status") == "broken")
    linked_files = final_state.get("linked_files", [])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Readiness Score", f"{score}/100", delta=grade)
    c2.metric("Total Links", total_links)
    c3.metric("Broken", broken, delta_color="inverse")
    c4.metric("Linked Files", len(linked_files))

    ready_label = "✅ SUBMISSION READY" if score >= 80 and broken == 0 else "⚠️ REVIEW NEEDED"
    st.info(f"**Grade {grade}** — {ready_label}")

    # Download linked files
    if linked_files:
        st.markdown("**Download linked documents:**")
        dl_cols = st.columns(min(len(linked_files), 4))
        for i, fp in enumerate(linked_files):
            fp = Path(fp)
            if fp.exists():
                with open(fp, "rb") as fh:
                    dl_cols[i % 4].download_button(
                        label=f"⬇ {fp.name}",
                        data=fh.read(),
                        file_name=fp.name,
                        mime=(
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                            if fp.suffix == ".docx" else "application/pdf"
                        ),
                    )

    # Download CSV report
    csv_path = output_dir / "validation_report.csv"
    if csv_path.exists():
        st.download_button(
            label="⬇ Download Validation Report (CSV)",
            data=csv_path.read_bytes(),
            file_name="validation_report.csv",
            mime="text/csv",
        )

    if final_state.get("error"):
        st.error(f"Pipeline error: {final_state['error']}")

    # Show link table
    links = final_state.get("links", [])
    if links:
        st.markdown("**Link records:**")
        import pandas as pd
        df = pd.DataFrame(links)[
            ["source_doc", "link_text", "target_doc", "target_anchor", "status", "confidence", "detected_by"]
        ] if links else pd.DataFrame()
        st.dataframe(df, use_container_width=True, height=300)


# ─────────────────────────────────────────────────────────────────────────────
# Main entrypoint
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:  # pragma: no cover
    """Streamlit app entrypoint."""
    _require_streamlit()

    st.set_page_config(
        page_title="Hyperlink Engine — QC Dashboard",
        page_icon="🔗",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ── Sidebar ────────────────────────────────────────────────────────────
    st.sidebar.title("🔗 Hyperlink Engine")
    st.sidebar.caption("QC Dashboard v2 (Plan Two)")

    page = st.sidebar.radio(
        "Navigate",
        options=["🚀 Run Pipeline", "Overview", "Module Matrix", "Link Inspector", "Export"],
        index=0,
    )

    # ── Run Pipeline (new Plan Two page) ──────────────────────────────────
    if page == "🚀 Run Pipeline":
        _render_run_pipeline()
        st.sidebar.divider()
        st.sidebar.caption("On-prem only. No data leaves this machine.")
        return

    # ── Legacy pages (load from report directory) ─────────────────────────
    default_dir = os.environ.get(
        "HYPERLINK_STREAMLIT_REPORT_DIR",
        str(Path("output/bench").resolve()),
    )
    report_dir_str = st.sidebar.text_input(
        "Report root directory",
        value=default_dir,
        help="Path to the timestamped output directory (e.g. output/bench/20260527T053700/reports)",
    )
    report_root = Path(report_dir_str)

    if not report_root.exists():
        st.error(f"Directory not found: `{report_root}`")
        st.stop()

    try:
        import pandas as pd  # noqa: PLC0415
        df = _load_dossier_csv(report_root)
    except ImportError:
        st.error("pandas is required for the dashboard. Install with: `pip install pandas`")
        st.stop()
        return

    if page == "Overview":
        _render_home(df)
    elif page == "Module Matrix":
        _render_module_matrix(df)
    elif page == "Link Inspector":
        _render_anomaly_browser(df)
    elif page == "Export":
        _render_export(df, report_root)

    st.sidebar.divider()
    st.sidebar.caption("On-prem only. No data leaves this machine.")


if __name__ == "__main__":  # pragma: no cover
    main()
