/* Hyperlink Engine — one-slide high-level architecture (Zensar house style)
 * Run: NODE_PATH="$(npm root -g)" node build_arch.js
 */
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const FA = require("react-icons/fa");

// ---------- palette ----------
const NAVY   = "16244A"; // deep navy — headers, sidebar, top cards, deploy
const STRIP  = "2A4178"; // medium navy — band left-label strips
const BLUE   = "2E5BA7"; // accent blue — icons on white cards, title word
const TEAL   = "13B5C9"; // teal pop — hero icon, injection accent
const ICE    = "E3ECF9"; // icon-circle fill on white cards
const LIGHT  = "EEF3FB"; // band container fill
const BORDER = "CBD8EE"; // card borders
const WHITE  = "FFFFFF";
const TEXT   = "16244A"; // dark text on white
const MUTED  = "5E6E90"; // subtitle on white
const SUBWHT = "C7D3EC"; // subtitle on navy
const HEAD   = "Calibri";

const makeShadow = () => ({ type: "outer", color: "1B2A52", blur: 4, offset: 1.5, angle: 135, opacity: 0.18 });

// ---------- icon rasteriser (memoised) ----------
const _cache = {};
async function icon(name, colorHex) {
  const key = name + colorHex;
  if (_cache[key]) return _cache[key];
  const Comp = FA[name];
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + colorHex, size: "256" }));
  const png = await sharp(Buffer.from(svg)).png().toBuffer();
  const data = "image/png;base64," + png.toString("base64");
  _cache[key] = data;
  return data;
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5
  pres.author = "Zensar";
  pres.title = "Hyperlink Engine — Reference Architecture";
  const s = pres.addSlide();
  s.background = { color: WHITE };

  // ---------- geometry ----------
  const CX = 3.3, CW = 8.13;          // center stack
  const SBX = 11.58, SBW = 1.5;       // right sidebar
  const LX = 0.3, LW = 2.85;          // left rail

  // ---------- header ----------
  s.addText([
    { text: "AI-Powered ", options: { color: NAVY } },
    { text: "Hyperlink Automation", options: { color: BLUE } },
    { text: " & Validation Engine", options: { color: NAVY } },
  ], { x: LX, y: 0.24, w: 10.4, h: 0.5, fontSize: 22, bold: true, fontFace: HEAD, align: "left", valign: "middle", margin: 0 });

  s.addText("On-Prem Reference Architecture  ·  Regulatory Submission Publishing (eCTD Modules 1–5)",
    { x: LX, y: 0.72, w: 10.4, h: 0.32, fontSize: 11, italic: true, color: MUTED, fontFace: HEAD, align: "left", valign: "middle", margin: 0 });

  s.addText("zensar", { x: 10.95, y: 0.26, w: 2.1, h: 0.5, fontSize: 24, bold: true, color: NAVY, fontFace: HEAD, align: "right", valign: "middle", margin: 0 });

  // ================= LEFT RAIL =================
  // hero tile
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: LX, y: 1.12, w: LW, h: 1.5, fill: { color: NAVY }, line: { type: "none" }, rectRadius: 0.08, shadow: makeShadow() });
  s.addImage({ data: await icon("FaProjectDiagram", TEAL), x: LX + LW / 2 - 0.31, y: 1.28, w: 0.62, h: 0.62 });
  s.addText("Hyperlink Engine", { x: LX, y: 1.98, w: LW, h: 0.3, fontSize: 14.5, bold: true, color: WHITE, fontFace: HEAD, align: "center", valign: "middle", margin: 0 });
  s.addText("6-layer on-prem AI pipeline", { x: LX, y: 2.28, w: LW, h: 0.26, fontSize: 9, color: SUBWHT, fontFace: HEAD, align: "center", valign: "middle", margin: 0 });

  // description
  s.addText("An on-prem AI engine that detects cross-references across 500+ regulatory documents, injects validated hyperlinks into Word, PDF & eCTD renditions, and scores submission readiness — with zero external API calls.",
    { x: LX + 0.02, y: 2.78, w: LW - 0.04, h: 1.6, fontSize: 10.5, color: TEXT, fontFace: HEAD, align: "left", valign: "top", lineSpacingMultiple: 1.05 });

  // stat chips
  const statChip = (y, big, label) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: LX, y, w: LW, h: 1.0, fill: { color: ICE }, line: { color: BORDER, width: 1 }, rectRadius: 0.07 });
    s.addText(big, { x: LX + 0.15, y: y + 0.08, w: LW - 0.3, h: 0.52, fontSize: 30, bold: true, color: BLUE, fontFace: HEAD, align: "left", valign: "middle", margin: 0 });
    s.addText(label, { x: LX + 0.16, y: y + 0.58, w: LW - 0.3, h: 0.36, fontSize: 9.5, color: NAVY, fontFace: HEAD, align: "left", valign: "top", margin: 0 });
  };
  statChip(4.50, "60–75%", "reduction in manual hyperlinking effort");
  statChip(5.60, "< 0.5%", "target broken-link rejection rate");

  // ================= TOP INPUT BAR =================
  const topY = 1.12, topH = 0.66;
  const topCards = [
    ["FaFileWord", "Documents", ".docx (Dosscriber) · PDF"],
    ["FaSitemap", "eCTD Backbone", "index.xml · regional XML"],
    ["FaPlug", "Integrations", "Dossplorer · CAPTIS APIs"],
  ];
  const tcW = (CW - 0.24) / 3;
  for (let i = 0; i < 3; i++) {
    const x = CX + i * (tcW + 0.12);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: topY, w: tcW, h: topH, fill: { color: NAVY }, line: { type: "none" }, rectRadius: 0.06, shadow: makeShadow() });
    s.addImage({ data: await icon(topCards[i][0], WHITE), x: x + 0.16, y: topY + 0.19, w: 0.28, h: 0.28 });
    s.addText(topCards[i][1], { x: x + 0.55, y: topY + 0.08, w: tcW - 0.65, h: 0.26, fontSize: 11, bold: true, color: WHITE, fontFace: HEAD, align: "left", valign: "middle", margin: 0 });
    s.addText(topCards[i][2], { x: x + 0.55, y: topY + 0.36, w: tcW - 0.62, h: 0.24, fontSize: 8, color: SUBWHT, fontFace: HEAD, align: "left", valign: "middle", margin: 0 });
  }

  // ================= MAJOR BANDS =================
  const stripW = 1.28, gap = 0.12;
  const cardAreaX = CX + stripW + gap;
  const cardAreaW = CW - stripW - gap;
  const cW4 = (cardAreaW - 3 * 0.1) / 4;
  const cardX = (i) => cardAreaX + i * (cW4 + 0.1);

  // generic white card
  async function whiteCard(x, y, w, h, iconName, iconColor, title, sub) {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: WHITE }, line: { color: BORDER, width: 1 }, rectRadius: 0.06, shadow: makeShadow() });
    s.addShape(pres.shapes.OVAL, { x: x + 0.1, y: y + 0.12, w: 0.32, h: 0.32, fill: { color: ICE }, line: { type: "none" } });
    s.addImage({ data: await icon(iconName, iconColor), x: x + 0.17, y: y + 0.19, w: 0.18, h: 0.18 });
    s.addText(title, { x: x + 0.48, y: y + 0.1, w: w - 0.55, h: 0.36, fontSize: 10, bold: true, color: NAVY, fontFace: HEAD, align: "left", valign: "middle", margin: 0 });
    s.addText(sub, { x: x + 0.1, y: y + 0.48, w: w - 0.2, h: h - 0.56, fontSize: 7.8, color: MUTED, fontFace: HEAD, align: "left", valign: "top", margin: 0, lineSpacingMultiple: 1.0 });
  }

  // band left label strip
  function bandStrip(y, h, label) {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: CX, y, w: stripW, h, fill: { color: STRIP }, line: { type: "none" }, rectRadius: 0.06 });
    s.addText(label, { x: CX, y, w: stripW, h, fontSize: 10.5, bold: true, color: WHITE, fontFace: HEAD, align: "center", valign: "middle", margin: 2 });
  }

  // band container
  function bandBox(y, h) {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: CX, y, w: CW, h, fill: { color: LIGHT }, line: { color: BORDER, width: 1 }, rectRadius: 0.07 });
  }

  // --- Band 1: Orchestration ---
  const b1y = 1.88, b1h = 1.18, b1cy = b1y + 0.1, b1ch = b1h - 0.2;
  bandBox(b1y, b1h);
  bandStrip(b1y, b1h, "Orchestration\n& Experience");
  await whiteCard(cardX(0), b1cy, cW4, b1ch, "FaProjectDiagram", BLUE, "LangGraph", "State machine · checkpoints");
  await whiteCard(cardX(1), b1cy, cW4, b1ch, "FaRobot", BLUE, "Agents", "Fast · Balanced · Max");
  await whiteCard(cardX(2), b1cy, cW4, b1ch, "FaStream", BLUE, "Pipeline", "Celery + Redis · cache");
  await whiteCard(cardX(3), b1cy, cW4, b1ch, "FaDesktop", BLUE, "Dashboard", "FastAPI + React · edit");

  // --- Band 2: AI Detection & Injection ---
  const b2y = 3.16, b2h = 1.42, b2cy = b2y + 0.1, b2ch = b2h - 0.2;
  bandBox(b2y, b2h);
  bandStrip(b2y, b2h, "AI Detection\n& Injection");
  await whiteCard(cardX(0), b2cy, cW4, b2ch, "FaCode", BLUE, "Regex", "Study IDs · §refs · tables");
  await whiteCard(cardX(1), b2cy, cW4, b2ch, "FaBrain", BLUE, "spaCy NER", "Custom entity model");
  await whiteCard(cardX(2), b2cy, cW4, b2ch, "FaMicrochip", BLUE, "Ollama LLM", "On-prem disambiguation");
  await whiteCard(cardX(3), b2cy, cW4, b2ch, "FaLink", TEAL, "Injection", "Word · PDF · eCTD xref");

  // --- Band 3: Ingestion, Parsing & Knowledge ---
  const b3y = 4.68, b3h = 1.30, b3cy = b3y + 0.1, b3ch = b3h - 0.2;
  bandBox(b3y, b3h);
  bandStrip(b3y, b3h, "Ingestion · Parsing\n& Knowledge");
  await whiteCard(cardX(0), b3cy, cW4, b3ch, "FaFileImport", BLUE, "Loaders", "docx · pdf · eCTD");
  await whiteCard(cardX(1), b3cy, cW4, b3ch, "FaAlignLeft", BLUE, "Parsers", "docx · PyMuPDF · lxml");
  await whiteCard(cardX(2), b3cy, cW4, b3ch, "FaShareAlt", BLUE, "Neo4j Graph", "Dossier · Doc · Ref nodes");
  await whiteCard(cardX(3), b3cy, cW4, b3ch, "FaDatabase", BLUE, "Redis Cache", "Per-doc SHA256");

  // ================= DEPLOYMENT STRIP =================
  const dY = 6.10, dH = 0.55;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: CX, y: dY, w: CW, h: dH, fill: { color: NAVY }, line: { type: "none" }, rectRadius: 0.06, shadow: makeShadow() });
  s.addImage({ data: await icon("FaServer", WHITE), x: CX + 0.2, y: dY + 0.17, w: 0.22, h: 0.22 });
  s.addText([
    { text: "Deployment   ", options: { bold: true, color: WHITE } },
    { text: "Local POC → On-Prem VPC   ·   Docker Compose   ·   Ollama   ·   Neo4j 5   ·   Redis 7   ·   No external APIs", options: { color: SUBWHT } },
  ], { x: CX + 0.5, y: dY, w: CW - 0.6, h: dH, fontSize: 9.2, fontFace: HEAD, align: "center", valign: "middle", margin: 0 });

  // ================= RIGHT SIDEBAR =================
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: SBX, y: 1.12, w: SBW, h: 0.46, fill: { color: STRIP }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText("Validation\n& Governance", { x: SBX, y: 1.12, w: SBW, h: 0.46, fontSize: 9, bold: true, color: WHITE, fontFace: HEAD, align: "center", valign: "middle", margin: 0 });

  const sbItems = [
    ["FaCheckCircle", "Existence & Target Validation"],
    ["FaExclamationTriangle", "Anomaly Detection"],
    ["FaEye", "Viewer Compatibility"],
    ["FaTachometerAlt", "Submission Readiness Score"],
    ["FaPalette", "Style Preservation"],
    ["FaClipboardCheck", "21 CFR Part 11 Audit Trail"],
    ["FaShieldAlt", "On-Prem / GxP"],
  ];
  const sbTop = 1.66, sbGap = 0.07;
  const sbH = (6.65 - sbTop - sbGap * (sbItems.length - 1)) / sbItems.length;
  for (let i = 0; i < sbItems.length; i++) {
    const y = sbTop + i * (sbH + sbGap);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: SBX, y, w: SBW, h: sbH, fill: { color: NAVY }, line: { type: "none" }, rectRadius: 0.05 });
    s.addImage({ data: await icon(sbItems[i][0], TEAL), x: SBX + 0.12, y: y + sbH / 2 - 0.11, w: 0.22, h: 0.22 });
    s.addText(sbItems[i][1], { x: SBX + 0.42, y, w: SBW - 0.52, h: sbH, fontSize: 8, bold: true, color: WHITE, fontFace: HEAD, align: "left", valign: "middle", margin: 0, lineSpacingMultiple: 0.95 });
  }

  // ================= FOOTER =================
  s.addText("Zensar Technologies   ·   AI-Powered Hyperlink Automation & Validation Engine   ·   On-Prem AI POC   ·   2026",
    { x: LX, y: 6.82, w: 12.8, h: 0.3, fontSize: 8, color: MUTED, fontFace: HEAD, align: "left", valign: "middle", margin: 0 });

  await pres.writeFile({ fileName: "Hyperlink_Engine_Architecture.pptx" });
  console.log("WROTE Hyperlink_Engine_Architecture.pptx");
})();
