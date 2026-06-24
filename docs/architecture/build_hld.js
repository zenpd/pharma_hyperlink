/* HLD Architecture (top-to-bottom, currently-working) + Tech Stack
 * Matches the deck's minimal template: title + top/bottom rules + date + page#.
 * Run: NODE_PATH="$(npm root -g)" node build_hld.js
 */
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const FA = require("react-icons/fa");
const SI = require("react-icons/si");

// palette (cohesive with the platform slide, restrained for the minimal template)
const NAVY = "16244A", STRIP = "2A4178", BLUE = "2E5BA7", TEAL = "13B5C9";
const ICE = "E3ECF9", LIGHT = "EEF3FB", BORDER = "CBD8EE", WHITE = "FFFFFF";
const TEXT = "16244A", MUTED = "5E6E90", RULE = "111111", GREY = "6B6B6B";
const TITLEC = "404040", HEAD = "Trebuchet MS", BODY = "Calibri";
const DATE = "6/5/2026";

const makeShadow = () => ({ type: "outer", color: "1B2A52", blur: 4, offset: 1.5, angle: 135, opacity: 0.16 });

const _cache = {};
function comp(name) { return FA[name] || SI[name]; }
async function icon(name, colorHex, fallback = "FaCube") {
  const key = name + colorHex;
  if (_cache[key]) return _cache[key];
  const C = comp(name) || comp(fallback) || FA.FaCube;
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(C, { color: "#" + colorHex, size: "256" }));
  const png = await sharp(Buffer.from(svg)).png().toBuffer();
  const data = "image/png;base64," + png.toString("base64");
  _cache[key] = data;
  return data;
}
const ml = (txt) => txt.split("\n").map((t, i, a) => ({ text: t, options: { breakLine: i < a.length - 1 } }));

function chrome(s, pres, title, page) {
  s.background = { color: WHITE };
  s.addText(title, { x: 0.55, y: 0.18, w: 10, h: 0.5, fontSize: 26, color: TITLEC, fontFace: HEAD, bold: false, align: "left", valign: "middle", margin: 0 });
  s.addShape(pres.shapes.LINE, { x: 0.55, y: 0.8, w: 12.2, h: 0, line: { color: RULE, width: 2.75 } });
  s.addShape(pres.shapes.LINE, { x: 0.55, y: 6.95, w: 12.2, h: 0, line: { color: RULE, width: 2.75 } });
  s.addText(DATE, { x: 11.0, y: 7.02, w: 1.1, h: 0.28, fontSize: 8, color: GREY, fontFace: BODY, align: "right", valign: "middle", margin: 0 });
  s.addText(String(page), { x: 12.2, y: 6.99, w: 0.55, h: 0.34, fontSize: 14, color: GREY, fontFace: BODY, align: "right", valign: "middle", margin: 0 });
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.author = "Zensar";
  pres.title = "Hyperlink Engine — HLD & Tech Stack";

  // ============================================================
  // SLIDE 1 — HLD - Architecture (top-to-bottom pipeline + rails)
  // ============================================================
  const s1 = pres.addSlide();
  chrome(s1, pres, "HLD - Architecture", 5);

  const LRX = 0.6, LRW = 2.7;     // left rail
  const CX = 3.5, CW = 6.3;       // center pipeline
  const RRX = 10.0, RRW = 2.75;   // right rail
  const topY = 1.0, botY = 6.7, railH = botY - topY;

  // ---- rails (light container + navy header) ----
  async function rail(x, w, header, items, accent) {
    s1.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: topY, w, h: railH, fill: { color: LIGHT }, line: { color: BORDER, width: 1 }, rectRadius: 0.07 });
    s1.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: topY, w, h: 0.5, fill: { color: NAVY }, line: { type: "none" }, rectRadius: 0.07 });
    s1.addText(header, { x, y: topY, w, h: 0.5, fontSize: 11.5, bold: true, color: WHITE, fontFace: HEAD, align: "center", valign: "middle", margin: 0 });
    s1.addText("cross-cutting", { x, y: topY + 0.5, w, h: 0.22, fontSize: 7.5, italic: true, color: MUTED, fontFace: BODY, align: "center", valign: "middle", margin: 0 });
    const startY = topY + 0.82, area = botY - startY - 0.08, step = area / items.length;
    for (let i = 0; i < items.length; i++) {
      const iy = startY + i * step;
      s1.addShape(pres.shapes.OVAL, { x: x + 0.16, y: iy + step / 2 - 0.18, w: 0.36, h: 0.36, fill: { color: WHITE }, line: { color: BORDER, width: 1 } });
      s1.addImage({ data: await icon(items[i][0], accent), x: x + 0.245, y: iy + step / 2 - 0.095, w: 0.19, h: 0.19 });
      s1.addText([{ text: items[i][1] + "\n", options: { bold: true, color: TEXT, fontSize: 10 } }, { text: items[i][2], options: { color: MUTED, fontSize: 8 } }],
        { x: x + 0.62, y: iy, w: w - 0.74, h: step, fontFace: BODY, align: "left", valign: "middle", margin: 0, lineSpacingMultiple: 0.98 });
    }
  }
  await rail(LRX, LRW, "Orchestration & Experience", [
    ["FaProjectDiagram", "LangGraph", "state machine + checkpoints"],
    ["FaStream", "Celery workers", "parallel fan-out"],
    ["FaBolt", "FastAPI", "REST API + SSE stream"],
    ["FaDesktop", "React + Streamlit", "Run Compare · inline edit"],
    ["FaSearch", "Snippet preview", "click-to-navigate"],
  ], BLUE);
  await rail(RRX, RRW, "Data & Governance", [
    ["FaShareAlt", "Neo4j 5", "Dossier · Doc · Reference"],
    ["FaDatabase", "Redis", "cache / broker"],
    ["FaClipboardCheck", "Audit trail", "audit.jsonl · GxP"],
    ["FaMicrochip", "Ollama", "on-prem LLM"],
    ["FaShieldAlt", "21 CFR Part 11", "no external APIs"],
  ], BLUE);

  // ---- central vertical pipeline ----
  const stages = [
    ["Ingestion", "Recursive folder upload · docx / pdf / eCTD loaders"],
    ["Parsing", "python-docx · PyMuPDF · lxml — run-level styling + blue-text scan"],
    ["AI Detection Cascade", "Regex patterns → spaCy NER → Ollama LLM (confidence-gated)"],
    ["Target Resolution", "Section / leaf resolver · Neo4j eCTD backbone"],
    ["Hyperlink Injection", "Word · PDF · eCTD xref — style-preserving _linked copies"],
    ["Validation & Anomaly", "Existence · target match · viewer compat · anomalies"],
    ["Reporting & Outputs", "Readiness score · CSV / XLSX · _linked.docx / .pdf"],
  ];
  const boxH = 0.62, gap = 0.21, cx = CX + CW / 2;
  for (let i = 0; i < stages.length; i++) {
    const y = topY + 0.05 + i * (boxH + gap);
    s1.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: CX, y, w: CW, h: boxH, fill: { color: WHITE }, line: { color: BORDER, width: 1.25 }, rectRadius: 0.06, shadow: makeShadow() });
    s1.addShape(pres.shapes.OVAL, { x: CX + 0.13, y: y + boxH / 2 - 0.18, w: 0.36, h: 0.36, fill: { color: NAVY }, line: { type: "none" } });
    s1.addText(String(i + 1), { x: CX + 0.13, y: y + boxH / 2 - 0.18, w: 0.36, h: 0.36, fontSize: 12, bold: true, color: WHITE, fontFace: HEAD, align: "center", valign: "middle", margin: 0 });
    s1.addText(stages[i][0], { x: CX + 0.62, y: y + 0.08, w: CW - 0.75, h: 0.26, fontSize: 11.5, bold: true, color: NAVY, fontFace: HEAD, align: "left", valign: "middle", margin: 0 });
    s1.addText(stages[i][1], { x: CX + 0.62, y: y + 0.33, w: CW - 0.75, h: 0.24, fontSize: 8.5, color: MUTED, fontFace: BODY, align: "left", valign: "middle", margin: 0 });
    if (i < stages.length - 1) {
      s1.addText("▼", { x: cx - 0.25, y: y + boxH - 0.02, w: 0.5, h: gap + 0.04, fontSize: 14, color: BLUE, fontFace: BODY, align: "center", valign: "middle", margin: 0 });
    }
  }

  // ============================================================
  // SLIDE 2 — Tech Stack (3 x 3 category grid)
  // ============================================================
  const s2 = pres.addSlide();
  chrome(s2, pres, "Tech Stack", 6);

  const cards = [
    ["SiPython", "Language & Tooling", "Python 3.11 · Poetry\nRuff · Black · mypy · pytest"],
    ["FaFileAlt", "Document Parsing", "python-docx · PyMuPDF\npdfplumber · lxml"],
    ["FaBrain", "AI Detection", "Regex patterns · spaCy NER\nsentence-transformers"],
    ["FaMicrochip", "Local LLM (on-prem)", "Ollama · llama3.2\nlitellm gateway · NVIDIA NIM (opt)"],
    ["FaLink", "Hyperlink Injection", "python-docx (w:hyperlink)\npikepdf · PyMuPDF"],
    ["FaProjectDiagram", "Orchestration", "LangGraph · Celery\nRedis broker"],
    ["SiNeo4j", "Data & Graph", "Neo4j 5 · NetworkX\nRedis 7"],
    ["SiFastapi", "API & Backend", "FastAPI · Uvicorn\nPydantic · structlog"],
    ["SiReact", "Frontend & Infra", "React 18 · Vite · TypeScript\nStreamlit · Docker Compose"],
  ];
  const gX = 0.6, gY = 1.0, gW = 12.15, gH = 5.8, gg = 0.22;
  const cardW = (gW - 2 * gg) / 3, cardH = (gH - 2 * gg) / 3;
  for (let i = 0; i < cards.length; i++) {
    const col = i % 3, row = Math.floor(i / 3);
    const x = gX + col * (cardW + gg), y = gY + row * (cardH + gg);
    s2.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: cardW, h: cardH, fill: { color: WHITE }, line: { color: BORDER, width: 1.25 }, rectRadius: 0.06, shadow: makeShadow() });
    s2.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.09, h: cardH, fill: { color: BLUE }, line: { type: "none" } });
    s2.addShape(pres.shapes.OVAL, { x: x + 0.26, y: y + 0.22, w: 0.46, h: 0.46, fill: { color: ICE }, line: { type: "none" } });
    s2.addImage({ data: await icon(cards[i][0], BLUE), x: x + 0.36, y: y + 0.32, w: 0.26, h: 0.26 });
    s2.addText(cards[i][1], { x: x + 0.85, y: y + 0.2, w: cardW - 1.0, h: 0.5, fontSize: 13, bold: true, color: NAVY, fontFace: HEAD, align: "left", valign: "middle", margin: 0 });
    s2.addText(ml(cards[i][2]), { x: x + 0.28, y: y + 0.82, w: cardW - 0.5, h: cardH - 0.95, fontSize: 10.5, color: MUTED, fontFace: BODY, align: "left", valign: "top", margin: 0, lineSpacingMultiple: 1.12 });
  }

  await pres.writeFile({ fileName: "HLD_Architecture_TechStack.pptx" });
  console.log("WROTE HLD_Architecture_TechStack.pptx");
})();
