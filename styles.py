"""
styles.py
---------
Gee-Luma UI design system.
Split-world theme: obsidian-black sidebar (mission control) +
bone-white main canvas (output stage).
Accent: electric green #00e676 — one colour, used sparingly.

Call inject_css() once at app startup.
"""

import streamlit as st
import base64
from pathlib import Path

# ---------------------------------------------------------------------------
# Master stylesheet
# ---------------------------------------------------------------------------
def _icon_data_uri(path: str = "icon.png") -> str:
    p = Path(path)
    if not p.exists():
        return ""  # fall back gracefully
    b64 = base64.b64encode(p.read_bytes()).decode()
    return f"data:image/png;base64,{b64}"

ICON_SRC = _icon_data_uri()


_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Space+Mono:wght@400;700&family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,400;1,9..144,300&display=swap');

/* ── DESIGN TOKENS ───────────────────────────────────────────────────── */
:root {
  /* Sidebar — obsidian world */
  --sb-bg:          #0a0a0a;
  --sb-surface:     #111111;
  --sb-raise:       #181818;
  --sb-border:      rgba(255,255,255,0.07);
  --sb-border-hi:   rgba(255,255,255,0.14);
  --sb-text:        #e8e8e8;
  --sb-muted:       #666666;
  --sb-faint:       #333333;

  /* Main canvas — bone white world */
  --cv-bg:          #f7f6f2;
  --cv-surface:     #ffffff;
  --cv-border:      rgba(0,0,0,0.08);
  --cv-border-hi:   rgba(0,0,0,0.16);
  --cv-text:        #111111;
  --cv-muted:       #666666;
  --cv-faint:       #eeede9;

  /* Single accent — electric green */
  --green:          #00e676;
  --green-dim:      rgba(0,230,118,0.12);
  --green-glow:     0 0 0 3px rgba(0,230,118,0.18);

  /* Shared */
  --radius-sm:      6px;
  --radius-md:      10px;
  --radius-lg:      16px;
  --radius-xl:      22px;

  /* Typography */
  --font-ui:   'Space Grotesk', sans-serif;
  --font-mono: 'Space Mono', monospace;
  --font-serif:'Fraunces', Georgia, serif;
}

/* ── GLOBAL RESET ────────────────────────────────────────────────────── */
html, body, [class*="css"], .stApp {
  font-family: var(--font-ui) !important;
}

/* ── MAIN CANVAS (right) ─────────────────────────────────────────────── */
.stApp {
  background: var(--cv-bg) !important;
  color: var(--cv-text) !important;
}

/* Subtle grid texture on main canvas */
.stApp::before {
  content: '';
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(rgba(0,0,0,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,0,0,0.025) 1px, transparent 1px);
  background-size: 32px 32px;
  pointer-events: none;
  z-index: 0;
}

/* Override Streamlit text defaults on the white canvas */
.stApp p, .stApp li, .stApp label,
.stApp [data-testid="stMarkdownContainer"] p {
  color: var(--cv-text) !important;
}

/* ── SIDEBAR (left) — obsidian ───────────────────────────────────────── */
section[data-testid="stSidebar"] {
  background: var(--sb-bg) !important;
  border-right: 1px solid var(--sb-border) !important;
}
section[data-testid="stSidebar"] > div {
  background: transparent !important;
}
section[data-testid="stSidebar"] * {
  color: var(--sb-text) !important;
}
section[data-testid="stSidebar"] label {
  color: var(--sb-muted) !important;
  font-family: var(--font-mono) !important;
  font-size: 0.65rem !important;
  letter-spacing: 0.12em !important;
  text-transform: uppercase !important;
}
section[data-testid="stSidebar"] .stSelectbox > div > div {
  background: var(--sb-surface) !important;
  border: 1px solid var(--sb-border) !important;
  border-radius: var(--radius-sm) !important;
  color: var(--sb-text) !important;
}
section[data-testid="stSidebar"] .stSelectbox > div > div:hover {
  border-color: var(--sb-border-hi) !important;
}
section[data-testid="stSidebar"] .stFileUploader {
  background: transparent !important;
}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
  background: var(--sb-surface) !important;
  border: 1px dashed var(--sb-border-hi) !important;
  border-radius: var(--radius-md) !important;
  transition: border-color 0.2s !important;
}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"]:hover {
  border-color: var(--green) !important;
}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] * {
  color: var(--sb-text) !important;
}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInstructions"] small {
  color: var(--sb-muted) !important;
}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {
  background: var(--sb-raise) !important;
  border: 1px solid var(--sb-border-hi) !important;
  color: var(--sb-text) !important;
  border-radius: var(--radius-sm) !important;
  font-family: var(--font-mono) !important;
  font-size: 0.68rem !important;
  letter-spacing: 0.05em !important;
  transition: border-color 0.2s !important;
}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button:hover {
  border-color: var(--green) !important;
}
section[data-testid="stSidebar"] [data-testid="stFileUploaderFile"] {
  background: var(--sb-raise) !important;
  border: 1px solid var(--sb-border) !important;
  border-radius: var(--radius-sm) !important;
}
section[data-testid="stSidebar"] .stButton > button {
  background: var(--sb-raise) !important;
  border: 1px solid var(--sb-border-hi) !important;
  color: var(--sb-text) !important;
  border-radius: var(--radius-sm) !important;
  font-family: var(--font-mono) !important;
  font-size: 0.72rem !important;
  letter-spacing: 0.06em !important;
  width: 100% !important;
  transition: background 0.2s !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
  background: var(--sb-faint) !important;
  border-color: var(--green) !important;
}
section[data-testid="stSidebar"] .stSuccess {
  background: rgba(0,230,118,0.08) !important;
  border: 1px solid rgba(0,230,118,0.3) !important;
  border-radius: var(--radius-sm) !important;
  color: var(--green) !important;
}
section[data-testid="stSidebar"] .stSuccess * { color: var(--green) !important; }
section[data-testid="stSidebar"] hr {
  border-color: var(--sb-border) !important;
}
section[data-testid="stSidebar"] .stExpander {
  background: var(--sb-surface) !important;
  border: 1px solid var(--sb-border) !important;
  border-radius: var(--radius-md) !important;
}
section[data-testid="stSidebar"] .stCaption,
section[data-testid="stSidebar"] .stText {
  color: var(--sb-muted) !important;
  font-family: var(--font-mono) !important;
  font-size: 0.68rem !important;
}

/* ── PAGE HEADER ─────────────────────────────────────────────────────── */
.el-header {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 40px 0 28px;
  border-bottom: 1px solid var(--cv-border);
  margin-bottom: 36px;
  position: relative;
}
.el-header::after {
  content: '';
  position: absolute;
  bottom: -1px; left: 0;
  width: 128px; height: 3px;
  background-image: repeating-linear-gradient(
    90deg,
    #0a0a0a 0px, #0a0a0a 9px,
    var(--green) 9px, var(--green) 11px,
    transparent 11px, transparent 20px
  );
}
.el-logo {
  width: 48px; height: 48px;
  background: #0a0a0a;
  border-radius: var(--radius-md);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  position: relative;
  overflow: visible;
}
.el-logo::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(135deg, transparent 40%, rgba(0,230,118,0.15));
}
.el-logo-text {
  font-family: var(--font-mono);
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--green);
  letter-spacing: 0.04em;
  position: relative;
  z-index: 1;
}
.el-title {
  font-family: var(--font-serif) !important;
  font-size: 2.1rem !important;
  font-weight: 300 !important;
  color: var(--cv-text) !important;
  letter-spacing: -0.02em;
  line-height: 1;
  margin: 0 !important; padding: 0 !important;
}
.el-title em {
  font-style: italic;
  color: #444;
}
.el-subtitle {
  font-family: var(--font-mono);
  font-size: 0.68rem;
  color: var(--cv-muted);
  letter-spacing: 0.14em;
  text-transform: uppercase;
  margin: 6px 0 0 0;
}
.el-badges {
  margin-left: auto;
  display: flex;
  gap: 6px;
  align-items: center;
}
.el-badge {
  font-family: var(--font-mono);
  font-size: 0.62rem;
  padding: 4px 9px;
  border-radius: 999px;
  border: 1px solid var(--cv-border-hi);
  color: var(--cv-muted);
  letter-spacing: 0.08em;
  white-space: nowrap;
}
.el-badge-live {
  border-color: var(--green);
  color: var(--green);
  background: var(--green-dim);
  position: relative;
  padding-left: 20px;
}
.el-badge-live::before {
  content: '';
  position: absolute;
  left: 8px;
  top: 50%; transform: translateY(-50%);
  width: 5px; height: 5px;
  border-radius: 50%;
  background: var(--green);
  animation: blink 1.6s ease-in-out infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.25; }
}

/* ── SIDEBAR WORDMARK ────────────────────────────────────────────────── */
.sb-wordmark {
  font-family: var(--font-mono);
  font-size: 0.6rem;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--sb-faint) !important;
  padding: 16px 0 20px;
  border-bottom: 1px solid var(--sb-border);
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.sb-wordmark::before {
  content: '';
  display: inline-block;
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--green);
  flex-shrink: 0;
}

/* ── SECTION DIVIDERS ────────────────────────────────────────────────── */
.el-section-label {
  font-family: var(--font-mono);
  font-size: 0.62rem;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--cv-muted);
  margin: 0 0 14px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.el-section-label::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--cv-border);
}

/* ── QUERY SYNTAX REFERENCE (now nested inside a native st.expander,
   which already supplies its own bordered container — so this only
   needs to style its inner content, not repeat the card chrome) ────── */
.el-guidance {
  padding: 4px 2px 2px;
}
.el-guidance h4 {
  display: none;
}
.el-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}
.el-tag {
  background: var(--cv-faint);
  border: 1px solid var(--cv-border);
  border-radius: var(--radius-sm);
  padding: 4px 12px;
  font-size: 0.76rem;
  color: var(--cv-text);
  transition: all 0.18s;
  cursor: default;
  line-height: 1.4;
}
.el-tag:hover {
  border-color: var(--cv-border-hi);
  background: var(--cv-surface);
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.el-tag-key {
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 0.65rem;
  color: #0a0a0a;
  margin-right: 4px;
  letter-spacing: 0.04em;
}
.el-cloud-tip {
  margin-top: 14px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: var(--green-dim);
  border: 1px solid rgba(0,230,118,0.25);
  border-radius: var(--radius-sm);
  padding: 7px 12px;
  font-size: 0.76rem;
  color: #1a5c35;
}
.el-cloud-tip-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--green);
  flex-shrink: 0;
}

/* ── TEXTAREA & TEXT INPUT ────────────────────────────────────────────── */
.stTextArea textarea {
  background: var(--cv-surface) !important;
  color: var(--cv-text) !important;
  border: 1px solid var(--cv-border-hi) !important;
  border-radius: var(--radius-md) !important;
  font-family: var(--font-ui) !important;
  font-size: 0.93rem !important;
  padding: 14px 16px !important;
  transition: border-color 0.2s, box-shadow 0.2s !important;
  resize: vertical !important;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important;
  line-height: 1.6 !important;
}
.stTextArea textarea:focus {
  border-color: #0a0a0a !important;
  box-shadow: var(--green-glow) !important;
  outline: none !important;
}
.stTextArea textarea::placeholder {
  color: #b0aea8 !important;
  font-style: italic;
}
.stTextArea label,
.stTextInput label {
  font-family: var(--font-mono) !important;
  font-size: 0.68rem !important;
  letter-spacing: 0.12em !important;
  text-transform: uppercase !important;
  color: var(--cv-muted) !important;
  font-weight: 400 !important;
}
.stTextInput input {
  background: var(--cv-surface) !important;
  color: var(--cv-text) !important;
  border: 1px solid var(--cv-border-hi) !important;
  border-radius: var(--radius-md) !important;
  font-family: var(--font-ui) !important;
  font-size: 0.9rem !important;
  padding: 10px 14px !important;
  transition: border-color 0.2s, box-shadow 0.2s !important;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important;
}
.stTextInput input:focus {
  border-color: #0a0a0a !important;
  box-shadow: var(--green-glow) !important;
  outline: none !important;
}

/* ── GENERATE BUTTON ──────────────────────────────────────────────────── */
.stButton > button[kind="primary"] {
  background: #0a0a0a !important;
  color: #ffffff !important;
  border: none !important;
  border-radius: var(--radius-md) !important;
  font-family: var(--font-mono) !important;
  font-size: 0.78rem !important;
  font-weight: 700 !important;
  letter-spacing: 0.1em !important;
  text-transform: uppercase !important;
  padding: 0.75rem 2.2rem !important;
  transition: all 0.22s cubic-bezier(0.4,0,0.2,1) !important;
  position: relative !important;
  overflow: hidden !important;
}
.stButton > button[kind="primary"]::after {
  content: '';
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 2px;
  background: var(--green);
  transform: scaleX(0);
  transition: transform 0.22s;
}
.stButton > button[kind="primary"]:hover {
  transform: translateY(-2px) !important;
  box-shadow: 0 8px 24px rgba(0,0,0,0.22) !important;
}
.stButton > button[kind="primary"]:hover::after {
  transform: scaleX(1);
}
.stButton > button[kind="primary"]:active {
  transform: translateY(0) !important;
  box-shadow: 0 2px 8px rgba(0,0,0,0.14) !important;
}

/* ── SECONDARY BUTTONS ────────────────────────────────────────────────── */
.stButton > button:not([kind="primary"]) {
  background: var(--cv-surface) !important;
  color: var(--cv-text) !important;
  border: 1px solid var(--cv-border-hi) !important;
  border-radius: var(--radius-md) !important;
  font-family: var(--font-mono) !important;
  font-size: 0.72rem !important;
  letter-spacing: 0.06em !important;
  transition: all 0.2s !important;
}
.stButton > button:not([kind="primary"]):hover {
  border-color: #0a0a0a !important;
  background: var(--cv-faint) !important;
}

/* ── DOWNLOAD BUTTON ──────────────────────────────────────────────────── */
.stDownloadButton > button {
  background: var(--cv-faint) !important;
  color: var(--cv-text) !important;
  border: 1px solid var(--cv-border-hi) !important;
  border-radius: var(--radius-md) !important;
  font-family: var(--font-mono) !important;
  font-size: 0.72rem !important;
  letter-spacing: 0.06em !important;
  transition: all 0.2s !important;
}
.stDownloadButton > button:hover {
  background: var(--cv-surface) !important;
  border-color: var(--green) !important;
  color: #1a5c35 !important;
  transform: translateY(-1px) !important;
  box-shadow: 0 4px 12px rgba(0,230,118,0.12) !important;
}

/* ── SELECTBOX (main) ─────────────────────────────────────────────────── */
.stSelectbox > div > div {
  background: var(--cv-surface) !important;
  border: 1px solid var(--cv-border-hi) !important;
  border-radius: var(--radius-md) !important;
  color: var(--cv-text) !important;
  font-family: var(--font-ui) !important;
  transition: border-color 0.2s !important;
}
.stSelectbox > div > div:hover {
  border-color: #0a0a0a !important;
}

/* ── METRIC CARDS ─────────────────────────────────────────────────────── */
.el-metric {
  background: var(--cv-surface);
  border: 1px solid var(--cv-border);
  border-radius: var(--radius-lg);
  padding: 18px 16px 16px;
  text-align: center;
  transition: all 0.22s;
  position: relative;
  overflow: hidden;
}
.el-metric::after {
  content: '';
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 2px;
  background: #0a0a0a;
  transform: scaleX(0);
  transition: transform 0.22s;
}
.el-metric:hover { transform: translateY(-3px); box-shadow: 0 8px 24px rgba(0,0,0,0.08); }
.el-metric:hover::after { transform: scaleX(1); }
.el-metric-value {
  font-family: var(--font-serif);
  font-size: 1.45rem;
  font-weight: 300;
  color: var(--cv-text);
  line-height: 1;
  margin: 0 0 5px;
}
.el-metric-label {
  font-family: var(--font-mono);
  font-size: 0.6rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--cv-muted);
}
.el-metric.accent .el-metric-value { color: #1a5c35; }
.el-metric.accent::after { background: var(--green); }

/* ── MAP IMAGE ────────────────────────────────────────────────────────── */
.stImage img {
  border-radius: var(--radius-lg) !important;
  border: 1px solid var(--cv-border) !important;
  box-shadow:
    0 1px 2px rgba(0,0,0,0.04),
    0 4px 16px rgba(0,0,0,0.07),
    0 16px 40px rgba(0,0,0,0.06) !important;
  transition: box-shadow 0.3s, transform 0.3s !important;
}
.stImage img:hover {
  box-shadow:
    0 2px 4px rgba(0,0,0,0.06),
    0 8px 32px rgba(0,0,0,0.1),
    0 24px 60px rgba(0,0,0,0.08) !important;
  transform: translateY(-2px) !important;
}

/* ── STATUS / EXPANDER ────────────────────────────────────────────────── */
.stStatus {
  background: var(--cv-surface) !important;
  border: 1px solid var(--cv-border) !important;
  border-radius: var(--radius-md) !important;
}
.stExpander {
  background: var(--cv-surface) !important;
  border: 1px solid var(--cv-border) !important;
  border-radius: var(--radius-md) !important;
  transition: border-color 0.2s !important;
}
.stExpander:hover { border-color: var(--cv-border-hi) !important; }
.stExpander summary {
  font-family: var(--font-mono) !important;
  font-size: 0.76rem !important;
  color: var(--cv-muted) !important;
  letter-spacing: 0.04em !important;
}

/* ── ALERT COLOURS ────────────────────────────────────────────────────── */
.stSuccess {
  background: rgba(0,230,118,0.07) !important;
  border: 1px solid rgba(0,230,118,0.28) !important;
  border-radius: var(--radius-md) !important;
  color: #1a5c35 !important;
}
.stInfo {
  background: rgba(0,0,0,0.03) !important;
  border: 1px solid var(--cv-border-hi) !important;
  border-radius: var(--radius-md) !important;
}
.stWarning {
  background: rgba(245,150,40,0.07) !important;
  border: 1px solid rgba(245,150,40,0.28) !important;
  border-radius: var(--radius-md) !important;
}
.stError {
  background: rgba(220,50,50,0.06) !important;
  border: 1px solid rgba(220,50,50,0.25) !important;
  border-radius: var(--radius-md) !important;
}

/* ── HR & CAPTION ─────────────────────────────────────────────────────── */
hr {
  border: none !important;
  border-top: 1px solid var(--cv-border) !important;
  margin: 32px 0 !important;
}
.stCaption {
  font-family: var(--font-mono) !important;
  font-size: 0.65rem !important;
  color: var(--cv-muted) !important;
  letter-spacing: 0.06em !important;
}

/* ── SCROLLBAR ────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: rgba(0,0,0,0.12);
  border-radius: 99px;
}
::-webkit-scrollbar-thumb:hover { background: rgba(0,0,0,0.22); }

/* ── SIDEBAR SCROLLBAR ────────────────────────────────────────────────── */
section[data-testid="stSidebar"] ::-webkit-scrollbar-thumb {
  background: rgba(255,255,255,0.1);
}

/* ── SATELLITE ANIMATION (decorative header element) ─────────────────── */
@keyframes orbit {
  from { transform: rotate(0deg) translateX(18px) rotate(0deg); }
  to   { transform: rotate(360deg) translateX(18px) rotate(-360deg); }
}
@keyframes orbit-wide {
  from { transform: rotate(0deg) translateX(30px) rotate(0deg); }
  to   { transform: rotate(360deg) translateX(30px) rotate(-360deg); }
}
.el-sat {
  display: inline-block;
  width: 5px; height: 5px;
  border-radius: 50%;
  background: var(--green);
  animation: orbit 4s linear infinite;
  margin-left: 2px;
  vertical-align: middle;
}
.el-logo-orbit {
  position: absolute;
  top: 50%; left: 50%;
  width: 4px; height: 4px;
  margin: -2px 0 0 -2px;
  border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 6px 1px rgba(0,230,118,0.65);
  animation: orbit-wide 6s linear infinite;
  pointer-events: none;
}

/* ── INPUT TITLE FIELD SPECIAL STYLE ─────────────────────────────────── */
.el-title-input-wrap .stTextInput input {
  font-family: var(--font-serif) !important;
  font-style: italic;
  font-size: 1rem !important;
  border-left: 3px solid #0a0a0a !important;
  border-top: none !important;
  border-right: none !important;
  border-bottom: 1px solid var(--cv-border-hi) !important;
  border-radius: 0 !important;
  background: transparent !important;
  box-shadow: none !important;
  padding-left: 12px !important;
}
.el-title-input-wrap .stTextInput input:focus {
  border-left-color: var(--green) !important;
  box-shadow: none !important;
}

/* ── REDUCED MOTION ───────────────────────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
  .el-sat, .el-logo-orbit, .el-badge-live::before {
    animation: none !important;
  }
  * {
    transition-duration: 0.001ms !important;
  }
}
</style>
"""


# ---------------------------------------------------------------------------
# Page header HTML
# ---------------------------------------------------------------------------
# The logo image is loaded from icon.png on disk (via ICON_SRC above). If that
# file isn't present in the deployment, we fall back to a text mark instead of
# an <img src=""> that renders as a broken-image icon.
_LOGO_INNER = (
    f'<img src="{ICON_SRC}" style="width:100%;height:100%;object-fit:cover;border-radius:10px;">'
    if ICON_SRC else
    '<div class="el-logo-text">GL</div>'
)

HEADER_HTML = f"""
<div class="el-header">
  <div class="el-logo">
    {_LOGO_INNER}
    <span class="el-logo-orbit"></span>
  </div>
  <div>
    <div class="el-title">Gee-<em>Luma</em></div>
    <div class="el-subtitle">GEE Map Studio &nbsp;·&nbsp; AI Agent &nbsp;·&nbsp; 200+ Indices</div>
  </div>
  <div class="el-badges">
    <span class="el-badge el-badge-live">Live</span>
    <span class="el-badge">GEE</span>
    <span class="el-badge">Spyndex</span>
    <span class="el-badge">CrewAI</span>
  </div>
</div>
"""

# ---------------------------------------------------------------------------
# Sidebar wordmark
# ---------------------------------------------------------------------------

SIDEBAR_WORDMARK = """
<div class="sb-wordmark">Gee-Luma &mdash; Mission Control</div>
"""

# ---------------------------------------------------------------------------
# Query guidance card
# ---------------------------------------------------------------------------

GUIDANCE_HTML = """
<div class="el-guidance">
  <h4>Query Parameters</h4>
  <div class="el-tags">
    <div class="el-tag"><span class="el-tag-key">INDEX</span> NDVI · EVI · NBR · kNDVI · MNDWI</div>
    <div class="el-tag"><span class="el-tag-key">SENSOR</span> Sentinel-2 · Landsat 8/9 · MODIS · S1-SAR</div>
    <div class="el-tag"><span class="el-tag-key">PERIOD</span> Jan–Mar 2024 · last 6 months · 2020–2022</div>
    <div class="el-tag"><span class="el-tag-key">REGION</span> Sri Lanka · Amazon · Sahel · Nile Delta</div>
    <div class="el-tag"><span class="el-tag-key">CLOUD %</span> max 20% cloud cover · cloud-free</div>
  </div>
  <div class="el-cloud-tip">
    <div class="el-cloud-tip-dot"></div>
    Append <strong>&ldquo;with cloud removal&rdquo;</strong> or <strong>&ldquo;cloud-free&rdquo;</strong> for pixel-level masking
  </div>
</div>
"""

# ---------------------------------------------------------------------------
# Section label helper
# ---------------------------------------------------------------------------

def section_label(text: str) -> str:
    return f'<div class="el-section-label">{text}</div>'


# ---------------------------------------------------------------------------
# Metric card helper
# ---------------------------------------------------------------------------

def metric_card(value: str, label: str, accent: bool = False) -> str:
    cls = "el-metric accent" if accent else "el-metric"
    return f"""
<div class="{cls}">
  <div class="el-metric-value">{value}</div>
  <div class="el-metric-label">{label}</div>
</div>"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def inject_css() -> None:
    """Inject the full Gee-Luma design system into the Streamlit app."""
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(HEADER_HTML, unsafe_allow_html=True)
    

