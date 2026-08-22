#!/usr/bin/env python3
"""Generate schema_viewer.html with embedded schema data."""

import json
from pathlib import Path

SCHEMA_DIR = Path(__file__).parent.parent / "schema_versions"
CACHE_DIR = Path(__file__).parent.parent / "cache"
OUT = Path(__file__).parent.parent / "schema_viewer.html"


def collect_data():
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from schema.version_store import SchemaStore

    store = SchemaStore(SCHEMA_DIR)

    acc_to_date = {}
    acc_to_form = {}
    for sub_path in CACHE_DIR.glob("*/submissions.json"):
        try:
            data = json.load(open(sub_path))
            for a, d, f in zip(
                data["filings"]["recent"]["accessionNumber"],
                data["filings"]["recent"]["filingDate"],
                data["filings"]["recent"]["form"],
            ):
                acc_to_date[a] = d
                acc_to_form[a] = f
        except Exception:
            pass

    versions = []
    for vid in store.list_versions():
        v = store.get_version(vid)
        if not v:
            continue
        versions.append({
            "id": v.version_id,
            "parent": v.parent_version_id,
            "filing": v.source_filing or "",
            "date": acc_to_date.get(v.source_filing, ""),
            "form": acc_to_form.get(v.source_filing, ""),
            "hash": v.content_hash,
            "taxonomy_year": v.taxonomy_year or "",
            "concepts": len(v.concepts),
            "std": sum(1 for c in v.concepts if c.namespace_type == "STANDARD"),
            "comp": sum(1 for c in v.concepts if c.namespace_type == "COMPANY"),
            "calc_arcs": len(v.calc_arcs),
            "dim_arcs": len(v.dimension_arcs),
            "unresolved": len(v.unresolved),
            "unresolved_names": [c.name for c in v.unresolved],
            "concept_names": [c.name for c in v.concepts],
            "standard_names": [c.name for c in v.concepts if c.namespace_type == "STANDARD"],
            "company_names": [c.name for c in v.concepts if c.namespace_type == "COMPANY"],
            "calc_arc_list": [
                {"p": a.parent_name, "c": a.child_name, "w": a.weight}
                for a in v.calc_arcs
            ],
            "dim_arc_list": [
                {"a": d.axis_name, "m": d.member_name, "ns": d.member_namespace_type}
                for d in v.dimension_arcs
            ],
        })
    return versions


def build_html(versions):
    data_json = json.dumps(versions, indent=None)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEC Schema Explorer</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0d1117; color: #c9d1d9; line-height: 1.5; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
h1 {{ font-size: 1.5rem; color: #f0f6fc; margin-bottom: 4px; }}
.subtitle {{ color: #8b949e; font-size: 0.9rem; margin-bottom: 24px; }}

/* Timeline */
.timeline {{ display: flex; gap: 4px; align-items: flex-end; margin-bottom: 32px; padding: 16px; background: #161b22; border-radius: 8px; border: 1px solid #30363d; overflow-x: auto; }}
.node {{ display: flex; flex-direction: column; align-items: center; cursor: pointer; min-width: 56px; transition: transform 0.15s; }}
.node:hover {{ transform: translateY(-2px); }}
.node.selected .bar {{ background: #58a6ff; border-color: #58a6ff; }}
.bar {{ width: 36px; background: #30363d; border-radius: 4px 4px 0 0; border: 1px solid #484f58; transition: background 0.15s, border-color 0.15s; min-height: 4px; }}
.bar-label {{ font-size: 0.65rem; color: #8b949e; margin-top: 4px; text-align: center; white-space: nowrap; }}
.bar-count {{ font-size: 0.7rem; color: #c9d1d9; font-weight: 600; margin-bottom: 2px; }}

/* Panels */
.panels {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
@media (max-width: 800px) {{ .panels {{ grid-template-columns: 1fr; }} }}
.panel {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }}
.panel h2 {{ font-size: 0.95rem; color: #f0f6fc; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }}
.panel h2 .badge {{ font-size: 0.7rem; padding: 2px 8px; border-radius: 12px; background: #30363d; color: #8b949e; }}

/* Stats */
.stat-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 16px; }}
.stat {{ text-align: center; padding: 8px; background: #0d1117; border-radius: 6px; }}
.stat .num {{ font-size: 1.4rem; font-weight: 700; color: #f0f6fc; }}
.stat .label {{ font-size: 0.7rem; color: #8b949e; }}

/* Lists */
.concept-list {{ max-height: 320px; overflow-y: auto; font-size: 0.8rem; }}
.concept-list div {{ padding: 3px 8px; border-radius: 4px; margin-bottom: 2px; }}
.concept-list div:hover {{ background: #1c2128; }}
.concept-list .std {{ color: #7ee787; }}
.concept-list .comp {{ color: #d2a8ff; }}
.concept-list .unres {{ color: #f85149; }}

/* Diff */
.diff-section {{ grid-column: 1 / -1; }}
.diff-item {{ display: flex; align-items: center; gap: 8px; padding: 4px 8px; font-size: 0.8rem; border-radius: 4px; margin-bottom: 2px; }}
.diff-item.add {{ background: #0d2818; }}
.diff-item.remove {{ background: #2d1214; }}
.diff-item.resolve {{ background: #0d1926; }}
.diff-icon {{ width: 16px; text-align: center; font-weight: 700; }}
.diff-icon.add {{ color: #3fb950; }}
.diff-icon.remove {{ color: #f85149; }}
.diff-icon.resolve {{ color: #58a6ff; }}

/* Trend chart */
.trend {{ grid-column: 1 / -1; }}
.trend-chart {{ display: flex; align-items: flex-end; gap: 2px; height: 120px; padding: 8px 0; }}
.trend-bar-wrap {{ flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; }}
.trend-bar {{ width: 100%; max-width: 48px; background: #f85149; border-radius: 3px 3px 0 0; transition: background 0.15s; min-height: 2px; }}
.trend-bar.low {{ background: #3fb950; }}
.trend-bar.mid {{ background: #d29922; }}
.trend-bar-label {{ font-size: 0.65rem; color: #8b949e; margin-top: 4px; }}
.trend-bar-count {{ font-size: 0.7rem; color: #c9d1d9; margin-bottom: 2px; }}

/* Metadata row */
.meta {{ display: flex; flex-wrap: wrap; gap: 12px; font-size: 0.8rem; color: #8b949e; margin-bottom: 12px; }}
.meta span {{ display: flex; align-items: center; gap: 4px; }}
.meta .val {{ color: #c9d1d9; }}

/* Scrollbar */
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: #0d1117; }}
::-webkit-scrollbar-thumb {{ background: #30363d; border-radius: 3px; }}
</style>
</head>
<body>
<div class="container">
  <h1>SEC Schema Explorer</h1>
  <div class="subtitle">APLD Debt Taxonomy — Version History &amp; Classification</div>

  <div class="timeline" id="timeline"></div>

  <div class="panels">
    <div class="panel" id="detail-panel">
      <h2>Version Details <span class="badge" id="version-badge"></span></h2>
      <div id="detail-content">Click a version above to inspect.</div>
    </div>
    <div class="panel" id="concepts-panel">
      <h2>Concepts</h2>
      <div id="concepts-content"></div>
    </div>
    <div class="panel diff-section" id="diff-panel">
      <h2>Changes from Previous Version</h2>
      <div id="diff-content"></div>
    </div>
    <div class="panel trend">
      <h2>Unresolved Concept Trend</h2>
      <div class="trend-chart" id="trend-chart"></div>
    </div>
  </div>
</div>

<script>
const DATA = {data_json};

let selectedIdx = 0;

function renderTimeline() {{
  const el = document.getElementById('timeline');
  const maxUnres = Math.max(...DATA.map(v => v.unresolved), 1);
  el.innerHTML = DATA.map((v, i) => {{
    const h = Math.max(8, (v.unresolved / maxUnres) * 100);
    const sel = i === selectedIdx ? ' selected' : '';
    const dateStr = v.date ? v.date.slice(5) : 'baseline';
    return `<div class="node${{sel}}" onclick="select(${{i}})">
      <div class="bar-count">${{v.unresolved}}</div>
      <div class="bar" style="height:${{h}}px"></div>
      <div class="bar-label">${{v.id}}</div>
      <div class="bar-label">${{dateStr}}</div>
    </div>`;
  }}).join('');
}}

function renderDetail() {{
  const v = DATA[selectedIdx];
  document.getElementById('version-badge').textContent = v.id;

  let meta = '';
  if (v.filing) {{
    meta = `<div class="meta">
      <span>Filing: <span class="val">${{v.filing}}</span></span>
      <span>Date: <span class="val">${{v.date || 'N/A'}}</span></span>
      <span>Form: <span class="val">${{v.form || 'N/A'}}</span></span>
      <span>Hash: <span class="val">${{v.hash.slice(0,12)}}</span></span>
      <span>Taxonomy: <span class="val">${{v.taxonomy_year || '?'}}</span></span>
    </div>`;
  }} else {{
    meta = `<div class="meta"><span>Standard taxonomy baseline (v0)</span></div>`;
  }}

  const stats = `<div class="stat-grid">
    <div class="stat"><div class="num">${{v.concepts}}</div><div class="label">Concepts</div></div>
    <div class="stat"><div class="num">${{v.calc_arcs}}</div><div class="label">Calc Arcs</div></div>
    <div class="stat"><div class="num">${{v.dim_arcs}}</div><div class="label">Dim Arcs</div></div>
    <div class="stat"><div class="num" style="color:${{v.unresolved > 20 ? '#f85149' : v.unresolved > 5 ? '#d29922' : '#3fb950'}}">${{v.unresolved}}</div><div class="label">Unresolved</div></div>
    <div class="stat"><div class="num">${{v.std}}</div><div class="label">Standard</div></div>
    <div class="stat"><div class="num">${{v.comp}}</div><div class="label">Company</div></div>
  </div>`;

  document.getElementById('detail-content').innerHTML = meta + stats;
}}

function renderConcepts() {{
  const v = DATA[selectedIdx];
  let html = '';

  if (v.standard_names.length) {{
    html += `<div style="font-size:0.75rem;color:#8b949e;margin:8px 0 4px">Standard (${{v.std}})</div>`;
    html += v.standard_names.map(n => `<div class="std">${{n}}</div>`).join('');
  }}

  if (v.company_names.length) {{
    html += `<div style="font-size:0.75rem;color:#8b949e;margin:8px 0 4px">Company Extensions (${{v.comp}})</div>`;
    html += v.company_names.map(n => `<div class="comp">${{n}}</div>`).join('');
  }}

  if (v.unresolved_names.length) {{
    html += `<div style="font-size:0.75rem;color:#8b949e;margin:8px 0 4px">Unresolved (${{v.unresolved}})</div>`;
    html += v.unresolved_names.map(n => `<div class="unres">${{n}}</div>`).join('');
  }}

  document.getElementById('concepts-content').innerHTML = html || '<div style="color:#8b949e">No concepts</div>';
}}

function renderDiff() {{
  if (selectedIdx === 0) {{
    document.getElementById('diff-content').innerHTML = '<div style="color:#8b949e">Baseline — no previous version.</div>';
    return;
  }}

  const prev = DATA[selectedIdx - 1];
  const curr = DATA[selectedIdx];

  const prevUnres = new Set(prev.unresolved_names);
  const currUnres = new Set(curr.unresolved_names);
  const prevConcepts = new Set(prev.concept_names);
  const currConcepts = new Set(curr.concept_names);

  let html = '';

  // New concepts
  const added = [...currConcepts].filter(n => !prevConcepts.has(n));
  if (added.length) {{
    html += `<div style="font-size:0.75rem;color:#8b949e;margin:4px 0">+${{added.length}} new concepts</div>`;
    added.slice(0, 10).forEach(n => {{
      html += `<div class="diff-item add"><span class="diff-icon add">+</span>${{n}}</div>`;
    }});
    if (added.length > 10) html += `<div style="font-size:0.75rem;color:#8b949e">... and ${{added.length - 10}} more</div>`;
  }}

  // Resolved
  const resolved = [...prevUnres].filter(n => !currUnres.has(n));
  if (resolved.length) {{
    html += `<div style="font-size:0.75rem;color:#8b949e;margin:8px 0 4px">~${{resolved.length}} resolved</div>`;
    resolved.slice(0, 10).forEach(n => {{
      html += `<div class="diff-item resolve"><span class="diff-icon resolve">~</span>${{n}}</div>`;
    }});
    if (resolved.length > 10) html += `<div style="font-size:0.75rem;color:#8b949e">... and ${{resolved.length - 10}} more</div>`;
  }}

  // New unresolved
  const newUnres = [...currUnres].filter(n => !prevUnres.has(n));
  if (newUnres.length) {{
    html += `<div style="font-size:0.75rem;color:#8b949e;margin:8px 0 4px">!${{newUnres.length}} newly unresolved</div>`;
    newUnres.slice(0, 10).forEach(n => {{
      html += `<div class="diff-item remove"><span class="diff-icon remove">!</span>${{n}}</div>`;
    }});
    if (newUnres.length > 10) html += `<div style="font-size:0.75rem;color:#8b949e">... and ${{newUnres.length - 10}} more</div>`;
  }}

  // Arc changes
  const calcDiff = curr.calc_arcs - prev.calc_arcs;
  const dimDiff = curr.dim_arcs - prev.dim_arcs;
  if (calcDiff !== 0 || dimDiff !== 0) {{
    html += `<div style="font-size:0.75rem;color:#8b949e;margin:8px 0 4px">Arc changes</div>`;
    if (calcDiff > 0) html += `<div class="diff-item add"><span class="diff-icon add">+</span>${{calcDiff}} calculation arcs</div>`;
    if (calcDiff < 0) html += `<div class="diff-item remove"><span class="diff-icon remove">-</span>${{-calcDiff}} calculation arcs</div>`;
    if (dimDiff > 0) html += `<div class="diff-item add"><span class="diff-icon add">+</span>${{dimDiff}} dimension arcs</div>`;
    if (dimDiff < 0) html += `<div class="diff-item remove"><span class="diff-icon remove">-</span>${{-dimDiff}} dimension arcs</div>`;
  }}

  if (!html) {{
    html = '<div style="color:#8b949e">No structural changes.</div>';
  }}

  document.getElementById('diff-content').innerHTML = html;
}}

function renderTrend() {{
  const el = document.getElementById('trend-chart');
  const maxUnres = Math.max(...DATA.map(v => v.unresolved), 1);
  el.innerHTML = DATA.map((v, i) => {{
    const h = Math.max(4, (v.unresolved / maxUnres) * 100);
    const cls = v.unresolved <= 5 ? 'low' : v.unresolved <= 20 ? 'mid' : '';
    const sel = i === selectedIdx ? 'outline: 2px solid #58a6ff;' : '';
    return `<div class="trend-bar-wrap" onclick="select(${{i}})" style="cursor:pointer">
      <div class="trend-bar-count">${{v.unresolved}}</div>
      <div class="trend-bar ${{cls}}" style="height:${{h}}px;${{sel}}"></div>
      <div class="trend-bar-label">${{v.id}}</div>
    </div>`;
  }}).join('');
}}

function select(idx) {{
  selectedIdx = idx;
  renderTimeline();
  renderDetail();
  renderConcepts();
  renderDiff();
  renderTrend();
}}

// Initial render
select(0);
</script>
</body>
</html>"""


if __name__ == "__main__":
    versions = collect_data()
    html = build_html(versions)
    OUT.write_text(html, encoding="utf-8")
    print(f"Written {len(html)} chars to {OUT}")
    print(f"Versions: {len(versions)}")
