"""Render the dependency-free, offline vocabulary-atlas explorer."""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from string import Template
from typing import Any


class _Template(Template):
    delimiter = "@@"


_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>@@title · RefSpec atlas explorer</title>
  <style>
    :root {
      --ink: #edf1ed;
      --muted: #9ba8a2;
      --faint: #68756f;
      --paper: #0c1211;
      --paper-raised: #111a18;
      --rule: #26332f;
      --rule-strong: #3b4c46;
      --accent: #e9b95f;
      --accent-soft: rgba(233, 185, 95, .12);
      --danger: #ee8b78;
      --focus: #8cd3c7;
      --serif: ui-serif, Georgia, Cambria, "Times New Roman", serif;
      --sans: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --mono: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
    }

    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 68% 32%, rgba(70, 111, 101, .12), transparent 34rem),
        var(--paper);
      font: 14px/1.45 var(--sans);
      overflow: hidden;
    }
    button, input { font: inherit; }
    button, a { -webkit-tap-highlight-color: transparent; }
    button:focus-visible, input:focus-visible, a:focus-visible, canvas:focus-visible {
      outline: 2px solid var(--focus);
      outline-offset: 2px;
    }
    .skip-link {
      position: fixed;
      top: .5rem;
      left: .5rem;
      z-index: 20;
      padding: .55rem .8rem;
      color: #07100e;
      background: var(--focus);
      transform: translateY(-160%);
    }
    .skip-link:focus { transform: translateY(0); }

    .shell {
      display: grid;
      grid-template-rows: auto 1fr auto;
      height: 100%;
      min-height: 0;
    }
    .appbar {
      display: grid;
      grid-template-columns: minmax(15rem, 1fr) auto auto;
      gap: 1.5rem;
      align-items: center;
      min-height: 74px;
      padding: .9rem 1.1rem .85rem 1.35rem;
      border-bottom: 1px solid var(--rule);
      background: rgba(12, 18, 17, .93);
      backdrop-filter: blur(12px);
    }
    .identity { min-width: 0; }
    .eyebrow {
      display: block;
      color: var(--accent);
      font: 600 10px/1.2 var(--mono);
      letter-spacing: .14em;
      text-transform: uppercase;
    }
    h1 {
      margin: .18rem 0 0;
      overflow: hidden;
      font: 500 clamp(1.15rem, 2vw, 1.55rem)/1.15 var(--serif);
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .seal {
      display: flex;
      gap: .55rem;
      align-items: center;
      color: var(--muted);
      white-space: nowrap;
    }
    .seal-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #80c99a;
      box-shadow: 0 0 0 4px rgba(128, 201, 154, .1);
    }
    .seal strong { color: var(--ink); font-size: .82rem; font-weight: 600; }
    .seal code { color: var(--faint); font: 11px/1.2 var(--mono); }
    .metrics { display: flex; gap: 1.35rem; }
    .metric { min-width: 4.3rem; text-align: right; }
    .metric b { display: block; font: 600 1rem/1 var(--mono); }
    .metric span { color: var(--faint); font-size: .7rem; letter-spacing: .04em; text-transform: uppercase; }

    .workspace {
      display: grid;
      grid-template-columns: 250px minmax(0, 1fr) 282px;
      min-height: 0;
    }
    .panel {
      min-height: 0;
      overflow: auto;
      scrollbar-color: var(--rule-strong) transparent;
    }
    .controls {
      padding: 1rem 1rem 1.5rem 1.2rem;
      border-right: 1px solid var(--rule);
      background: rgba(14, 21, 20, .78);
    }
    .inspector {
      padding: 1rem 1.1rem 1.5rem;
      border-left: 1px solid var(--rule);
      background: rgba(14, 21, 20, .82);
    }
    .panel h2, .panel h3 {
      margin: 0;
      font-size: .72rem;
      font-weight: 650;
      letter-spacing: .1em;
      text-transform: uppercase;
    }
    .panel h2 { color: var(--ink); }
    .panel h3 { color: var(--faint); }
    .control-section {
      padding: 1rem 0;
      border-bottom: 1px solid var(--rule);
    }
    .control-section:last-child { border-bottom: 0; }
    .search-wrap { position: relative; margin-top: .7rem; }
    #search {
      width: 100%;
      min-height: 42px;
      padding: .65rem 2rem .65rem .72rem;
      color: var(--ink);
      border: 1px solid var(--rule-strong);
      border-radius: 3px;
      background: #0a100f;
    }
    #search::placeholder { color: #63716c; }
    .key {
      position: absolute;
      top: 50%;
      right: .6rem;
      color: var(--faint);
      font: 11px/1 var(--mono);
      transform: translateY(-50%);
    }
    .results { display: grid; gap: 1px; margin-top: .45rem; }
    .result {
      width: 100%;
      padding: .48rem .1rem;
      color: var(--ink);
      border: 0;
      border-bottom: 1px solid rgba(38, 51, 47, .7);
      background: transparent;
      text-align: left;
      cursor: pointer;
    }
    .result:hover { color: var(--accent); }
    .result span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .result small { color: var(--faint); font-size: .7rem; }
    .filter-list { display: grid; gap: .58rem; margin-top: .75rem; }
    .filter {
      display: grid;
      grid-template-columns: 14px 1fr auto;
      gap: .55rem;
      align-items: center;
      min-height: 26px;
      color: var(--muted);
      cursor: pointer;
    }
    .release-filter { grid-template-columns: 14px 9px minmax(0, 1fr) auto; }
    .filter input { width: 14px; height: 14px; margin: 0; accent-color: var(--accent); }
    .filter .swatch { width: 9px; height: 9px; border-radius: 50%; background: var(--swatch); }
    .filter .label { overflow: hidden; color: var(--ink); text-overflow: ellipsis; white-space: nowrap; }
    .filter small { color: var(--faint); font: 10px/1 var(--mono); }
    .edge-key {
      width: 20px;
      height: 0;
      border-top: 2px solid var(--edge-color);
    }
    .edge-key.mapping { border-top-style: dashed; }
    .hint { margin: .7rem 0 0; color: var(--faint); font-size: .75rem; }

    .stage { position: relative; min-width: 0; min-height: 0; overflow: hidden; }
    #graph {
      display: block;
      width: 100%;
      height: 100%;
      opacity: 0;
      cursor: grab;
      transition: opacity .45s ease;
      touch-action: none;
    }
    #graph.ready { opacity: 1; }
    #graph.panning { cursor: grabbing; }
    .graph-tools {
      position: absolute;
      top: .75rem;
      right: .75rem;
      display: flex;
      overflow: hidden;
      border: 1px solid var(--rule-strong);
      border-radius: 3px;
      background: rgba(12, 18, 17, .92);
    }
    .graph-tools button {
      width: 38px;
      height: 38px;
      padding: 0;
      color: var(--muted);
      border: 0;
      border-right: 1px solid var(--rule);
      background: transparent;
      cursor: pointer;
    }
    .graph-tools button:last-child { border-right: 0; }
    .graph-tools button:hover { color: var(--accent); background: var(--accent-soft); }
    .mobile-only { display: none; }
    .legend-note {
      position: absolute;
      bottom: .8rem;
      left: .9rem;
      max-width: min(34rem, calc(100% - 1.8rem));
      margin: 0;
      color: var(--faint);
      font: 10px/1.45 var(--mono);
      pointer-events: none;
    }
    .tooltip {
      position: absolute;
      z-index: 4;
      max-width: 260px;
      padding: .45rem .6rem;
      color: var(--ink);
      border: 1px solid var(--rule-strong);
      background: rgba(8, 13, 12, .96);
      box-shadow: 0 8px 26px rgba(0, 0, 0, .3);
      font-size: .78rem;
      pointer-events: none;
      transform: translate(12px, 12px);
    }
    .tooltip[hidden] { display: none; }
    .tooltip small { display: block; color: var(--faint); }

    .empty-state { margin-top: 1.4rem; color: var(--muted); }
    .empty-state strong { display: block; margin-bottom: .35rem; color: var(--ink); font: 500 1.15rem/1.25 var(--serif); }
    .inspector-content[hidden], .empty-state[hidden] { display: none; }
    .node-kicker { margin: 1.1rem 0 .25rem; color: var(--accent); font: 10px/1.2 var(--mono); text-transform: uppercase; }
    .node-title { margin: 0; font: 500 1.3rem/1.2 var(--serif); overflow-wrap: anywhere; }
    .node-release { display: flex; gap: .45rem; align-items: center; margin: .55rem 0 1rem; color: var(--muted); }
    .node-release i { width: 8px; height: 8px; border-radius: 50%; background: var(--node-color); }
    .facts { display: grid; grid-template-columns: 5.2rem 1fr; gap: .45rem .65rem; margin: 0; }
    .facts dt { color: var(--faint); font-size: .72rem; }
    .facts dd { margin: 0; color: var(--muted); overflow-wrap: anywhere; }
    .iri {
      display: block;
      max-height: 5.5rem;
      overflow: auto;
      color: var(--muted);
      font: 10px/1.45 var(--mono);
      text-decoration: none;
    }
    a.iri:hover { color: var(--accent); }
    .copy-button {
      margin-top: .65rem;
      padding: .4rem .55rem;
      color: var(--muted);
      border: 1px solid var(--rule-strong);
      border-radius: 3px;
      background: transparent;
      cursor: pointer;
    }
    .copy-button:hover { color: var(--ink); border-color: var(--accent); }
    .connections { display: grid; gap: .35rem; margin-top: .7rem; }
    .connection {
      width: 100%;
      padding: .5rem .55rem;
      color: var(--muted);
      border: 0;
      border-left: 2px solid var(--connection-color);
      background: rgba(255, 255, 255, .02);
      text-align: left;
      cursor: pointer;
    }
    .connection:hover { color: var(--ink); background: rgba(255, 255, 255, .045); }
    .connection b { display: block; color: inherit; font-size: .78rem; font-weight: 550; }
    .connection small { color: var(--faint); }
    /* Why the gate decided, under the decision it explains. Text only: these
       are two machines' words, not another thing to click. */
    .connection-group { display: grid; gap: .3rem; }
    .connection-reason {
      margin: 0 0 0 .55rem;
      padding-left: .5rem;
      border-left: 1px solid var(--rule);
      color: var(--faint);
      font-size: .72rem;
      line-height: 1.45;
    }
    .connection-reason b { color: var(--muted); font-weight: 550; }

    .provenance {
      display: grid;
      grid-template-columns: 250px minmax(0, 1fr) auto;
      align-items: center;
      min-height: 45px;
      border-top: 1px solid var(--rule);
      color: var(--faint);
      background: #0a100f;
      font-size: .72rem;
    }
    .provenance > * { padding: .65rem 1.1rem; }
    .provenance summary { color: var(--muted); cursor: pointer; }
    .provenance details[open] {
      position: absolute;
      right: 1rem;
      bottom: 3rem;
      left: 1rem;
      z-index: 8;
      padding: 1rem;
      border: 1px solid var(--rule-strong);
      background: #0a100f;
      box-shadow: 0 14px 50px rgba(0, 0, 0, .4);
    }
    .pin-grid { display: grid; grid-template-columns: 9rem 1fr; gap: .4rem .8rem; margin-top: .8rem; }
    .pin-grid code { overflow-wrap: anywhere; color: var(--muted); font: 10px/1.4 var(--mono); }
    .downloads { display: flex; gap: .9rem; justify-content: flex-end; white-space: nowrap; }
    .downloads a { color: var(--muted); text-decoration: none; }
    .downloads a:hover { color: var(--accent); }

    @media (max-width: 940px) {
      .workspace { grid-template-columns: 220px minmax(0, 1fr); }
      .inspector {
        position: absolute;
        top: 74px;
        right: 0;
        bottom: 45px;
        z-index: 6;
        width: min(310px, 86vw);
        box-shadow: -12px 0 40px rgba(0, 0, 0, .32);
        transform: translateX(100%);
        transition: transform .2s ease;
      }
      .inspector.open { transform: translateX(0); }
      .metrics .metric:nth-child(-n+2) { display: none; }
      .provenance { grid-template-columns: 220px minmax(0, 1fr); }
      .downloads { display: none; }
    }
    @media (max-width: 660px) {
      body { overflow: auto; }
      .shell { min-height: 100%; height: auto; grid-template-rows: auto minmax(36rem, 1fr) auto; }
      .appbar { grid-template-columns: minmax(0, 1fr) auto; gap: .8rem; }
      .seal code, .metrics { display: none; }
      .workspace { position: relative; grid-template-columns: 1fr; min-height: 36rem; }
      .controls {
        position: absolute;
        top: .6rem;
        left: .6rem;
        z-index: 5;
        width: min(230px, calc(100vw - 1.2rem));
        max-height: calc(100% - 1.2rem);
        border: 1px solid var(--rule-strong);
        box-shadow: 0 12px 36px rgba(0, 0, 0, .32);
        transform: translateX(calc(-100% - 1rem));
        transition: transform .2s ease;
      }
      .controls.open { transform: translateX(0); }
      .provenance { grid-template-columns: 1fr; }
      .provenance > :first-child { display: none; }
      .graph-tools { top: .6rem; right: .6rem; }
      .mobile-only { display: block; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; }
    }
  </style>
</head>
<body>
  <a class="skip-link" href="#graph">Skip to graph</a>
  <div class="shell">
    <header class="appbar">
      <div class="identity">
        <span class="eyebrow">RefSpec vocabulary atlas</span>
        <h1>@@title</h1>
      </div>
      <div class="seal" aria-label="Atlas verified before publication">
        <span class="seal-dot" aria-hidden="true"></span>
        <span><strong>Sealed input</strong><br><code id="short-id"></code></span>
      </div>
      <div class="metrics" aria-label="Atlas totals">
        <div class="metric"><b id="metric-sources">—</b><span>sources</span></div>
        <div class="metric"><b id="metric-quads">—</b><span>quads</span></div>
        <div class="metric"><b id="metric-mappings">—</b><span>mappings</span></div>
      </div>
    </header>

    <main class="workspace">
      <aside class="panel controls" id="controls" aria-label="Graph controls">
        <h2>Explore the view</h2>
        <section class="control-section">
          <h3>Find a concept</h3>
          <div class="search-wrap">
            <input id="search" type="search" autocomplete="off" placeholder="Label or identifier" aria-label="Find a concept">
            <span class="key" aria-hidden="true">/</span>
          </div>
          <div class="results" id="search-results" aria-live="polite"></div>
        </section>
        <section class="control-section">
          <h3>Reference releases</h3>
          <div class="filter-list" id="release-filters"></div>
        </section>
        <section class="control-section">
          <h3>Relationships</h3>
          <div class="filter-list">
            <label class="filter">
              <input type="checkbox" data-edge="qualifiedMapping" checked>
              <span class="edge-key mapping" style="--edge-color:#e9b95f" aria-hidden="true"></span>
              <span><span class="label">Qualified mapping</span><small id="count-qualified"></small></span>
            </label>
            <label class="filter">
              <input type="checkbox" data-edge="sharedLabel" checked>
              <span class="edge-key" style="--edge-color:#6dc8bb" aria-hidden="true"></span>
              <span><span class="label">Shared label</span><small id="count-shared"></small></span>
            </label>
            <label class="filter">
              <input type="checkbox" data-edge="broader" checked>
              <span class="edge-key" style="--edge-color:#75847e" aria-hidden="true"></span>
              <span><span class="label">Broader concept</span><small id="count-broader"></small></span>
            </label>
            <label class="filter">
              <input type="checkbox" data-edge="related" checked>
              <span class="edge-key" style="--edge-color:#8eafd5" aria-hidden="true"></span>
              <span><span class="label">Related concept</span><small id="count-related"></small></span>
            </label>
            <label class="filter">
              <input type="checkbox" data-edge="use" checked>
              <span class="edge-key mapping" style="--edge-color:#c497cf" aria-hidden="true"></span>
              <span><span class="label">USE — preferred term</span><small id="count-use"></small></span>
            </label>
            <label class="filter">
              <input type="checkbox" data-edge="replacedBy" checked>
              <span class="edge-key" style="--edge-color:#ee8b78" aria-hidden="true"></span>
              <span><span class="label">Replaced by</span><small id="count-replaced"></small></span>
            </label>
            <label class="filter">
              <input type="checkbox" data-edge="rejectedCandidate">
              <span class="edge-key mapping" style="--edge-color:#8a6a63" aria-hidden="true"></span>
              <span><span class="label">Rejected candidate</span><small id="count-rejected"></small></span>
            </label>
          </div>
          <p class="hint">Equal labels are discovery signals. They are not qualified concept mappings.</p>
        </section>
        <section class="control-section">
          <h3>View boundary</h3>
          <p class="hint" id="selection-note"></p>
        </section>
      </aside>

      <section class="stage" id="stage" aria-label="Vocabulary graph">
        <canvas id="graph" tabindex="0" aria-describedby="graph-description"></canvas>
        <p id="graph-description" class="legend-note">Drag to pan. Scroll or use the controls to zoom. Select a node for exact source and relationship details.</p>
        <div class="graph-tools" aria-label="Graph view controls">
          <button class="mobile-only" type="button" id="toggle-controls" aria-label="Show filters">☰</button>
          <button type="button" id="zoom-in" aria-label="Zoom in">＋</button>
          <button type="button" id="zoom-out" aria-label="Zoom out">−</button>
          <button type="button" id="fit-view" aria-label="Fit graph to view">⌂</button>
        </div>
        <div class="tooltip" id="tooltip" hidden></div>
      </section>

      <aside class="panel inspector" id="inspector" aria-label="Concept inspector">
        <h2>Concept inspector</h2>
        <div class="empty-state" id="empty-inspector">
          <strong>Select a node</strong>
          Search by label, or choose a point in the graph to inspect its exact identifier and atlas relationships.
        </div>
        <div class="inspector-content" id="inspector-content" hidden>
          <p class="node-kicker" id="node-role"></p>
          <h3 class="node-title" id="node-title"></h3>
          <p class="node-release"><i id="node-swatch"></i><span id="node-release"></span></p>
          <dl class="facts">
            <dt>Identifier</dt>
            <dd><a class="iri" id="node-iri"></a><button class="copy-button" type="button" id="copy-iri">Copy IRI</button></dd>
            <dt id="notation-term" hidden>Notation</dt><dd id="notation-value" hidden></dd>
            <dt>Shown links</dt><dd id="node-link-count"></dd>
          </dl>
          <section class="control-section" id="node-notes" hidden>
            <h3>Source notes</h3>
            <p class="hint" id="node-definition" hidden></p>
            <p class="hint" id="node-scope-note" hidden></p>
          </section>
          <section class="control-section">
            <h3>Relationships in this view</h3>
            <div class="connections" id="connections"></div>
          </section>
        </div>
      </aside>
    </main>

    <footer class="provenance">
      <div><span id="view-count"></span> shown from the sealed atlas</div>
      <details>
        <summary>Provenance and exact pins</summary>
        <div class="pin-grid">
          <span>Atlas ID</span><code id="pin-id"></code>
          <span>Manifest</span><code id="pin-manifest"></code>
          <span>N-Quads</span><code id="pin-output"></code>
          <span>Selection</span><code id="pin-selection"></code>
        </div>
      </details>
      <nav class="downloads" aria-label="Atlas downloads">
        <a href="atlas-manifest.json" download>Manifest</a>
        <a href="atlas.nq.gz" download>N-Quads · gzip</a>
        <a href="atlas-explorer.json" download>Explorer data</a>
        <a href="publication-manifest.json" download>Publication record</a>
      </nav>
    </footer>
  </div>

  <noscript>This explorer needs JavaScript to draw the bounded graph. The atlas files and publication record remain downloadable.</noscript>
  <script id="atlas-data" type="application/json">@@atlas_data</script>
  <script>
  (() => {
    "use strict";

    const data = JSON.parse(document.getElementById("atlas-data").textContent);
    const canvas = document.getElementById("graph");
    const stage = document.getElementById("stage");
    const ctx = canvas.getContext("2d", { alpha: true });
    const tooltip = document.getElementById("tooltip");
    const search = document.getElementById("search");
    const resultBox = document.getElementById("search-results");
    const releaseFilters = document.getElementById("release-filters");
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const palette = ["#74c7b8", "#efb65d", "#e77d6d", "#8eafd5", "#b3c76d", "#c497cf", "#67b6d4"];
    const edgeColors = { qualifiedMapping: "#e9b95f", sharedLabel: "#6dc8bb", broader: "#75847e", related: "#8eafd5", use: "#c497cf", replacedBy: "#ee8b78", rejectedCandidate: "#8a6a63" };
    const edgeLabels = { qualifiedMapping: "qualified mapping", sharedLabel: "shared label", broader: "broader concept", related: "related concept", use: "USE — preferred term", replacedBy: "replaced by", rejectedCandidate: "rejected candidate" };
    const edgeAlpha = { qualifiedMapping: .52, sharedLabel: .24, broader: .2, related: .18, use: .6, replacedBy: .65, rejectedCandidate: .3 };
    const edgeWidth = { qualifiedMapping: 1.5, sharedLabel: .8, broader: .8, related: .7, use: 1.3, replacedBy: 1.3, rejectedCandidate: .9 };
    const releaseById = new Map(data.releases.map((release, index) => [release.id, { ...release, index, color: palette[index % palette.length] }]));
    const nodeById = new Map(data.nodes.map(node => [node.id, { ...node, x: 0, y: 0 }]));
    const adjacency = new Map(data.nodes.map(node => [node.id, []]));
    data.edges.forEach(edge => {
      if (adjacency.has(edge.source)) adjacency.get(edge.source).push({ edge, other: edge.target });
      if (adjacency.has(edge.target)) adjacency.get(edge.target).push({ edge, other: edge.source });
    });

    const state = {
      activeReleases: new Set(data.releases.map(release => release.id)),
      activeEdges: new Set(["qualifiedMapping", "sharedLabel", "broader", "related", "use", "replacedBy"]),
      selected: null,
      hover: null,
      matches: new Set(),
      query: "",
      view: { x: 0, y: 0, k: 1 },
      width: 1,
      height: 1,
      dpr: 1,
      panning: false,
      dragStart: null,
      lastPointer: null
    };

    function formatNumber(value) { return new Intl.NumberFormat("en-US").format(value); }
    function shortId(value) {
      const tail = value.split(":").pop();
      return tail.length > 16 ? `${tail.slice(0, 8)}…${tail.slice(-6)}` : tail;
    }
    function worldToScreen(node) {
      return { x: node.x * state.view.k + state.view.x, y: node.y * state.view.k + state.view.y };
    }
    function screenToWorld(x, y) {
      return { x: (x - state.view.x) / state.view.k, y: (y - state.view.y) / state.view.k };
    }
    function isNodeVisible(node) { return state.activeReleases.has(node.releaseId); }
    function isEdgeVisible(edge) {
      const source = nodeById.get(edge.source);
      const target = nodeById.get(edge.target);
      return state.activeEdges.has(edge.type) && source && target && isNodeVisible(source) && isNodeVisible(target);
    }
    function nodeRadius(node) {
      if (node.roles.includes("mappingEndpoint")) return 5.2;
      if (node.roles.includes("sharedLabel")) return 4.2;
      return 3.4;
    }

    function layout() {
      const worldWidth = Math.max(1050, data.releases.length * 330);
      const worldHeight = 780;
      data.releases.forEach((release, releaseIndex) => {
        const members = data.nodes
          .filter(node => node.releaseId === release.id)
          .sort((a, b) => a.label.localeCompare(b.label) || a.id.localeCompare(b.id));
        const angle = data.releases.length === 1 ? 0 : (Math.PI * 2 * releaseIndex / data.releases.length) - Math.PI / 2;
        const cx = data.releases.length <= 2
          ? worldWidth * ((releaseIndex + 1) / (data.releases.length + 1))
          : worldWidth / 2 + Math.cos(angle) * worldWidth * .31;
        const cy = data.releases.length <= 2 ? worldHeight / 2 : worldHeight / 2 + Math.sin(angle) * worldHeight * .29;
        members.forEach((value, index) => {
          const node = nodeById.get(value.id);
          const theta = index * 2.399963229728653;
          const radius = 13.5 * Math.sqrt(index);
          node.x = cx + Math.cos(theta) * radius;
          node.y = cy + Math.sin(theta) * radius;
        });
      });
    }

    function bounds() {
      const visible = data.nodes.map(node => nodeById.get(node.id)).filter(isNodeVisible);
      if (!visible.length) return { minX: 0, maxX: 1, minY: 0, maxY: 1 };
      return {
        minX: Math.min(...visible.map(node => node.x)),
        maxX: Math.max(...visible.map(node => node.x)),
        minY: Math.min(...visible.map(node => node.y)),
        maxY: Math.max(...visible.map(node => node.y))
      };
    }

    function fitView() {
      const box = bounds();
      const padding = 80;
      const width = Math.max(1, box.maxX - box.minX);
      const height = Math.max(1, box.maxY - box.minY);
      const scale = Math.max(.18, Math.min(2.3, Math.min((state.width - padding * 2) / width, (state.height - padding * 2) / height)));
      state.view.k = scale;
      state.view.x = state.width / 2 - ((box.minX + box.maxX) / 2) * scale;
      state.view.y = state.height / 2 - ((box.minY + box.maxY) / 2) * scale;
      draw();
    }

    function resize() {
      const rect = stage.getBoundingClientRect();
      state.width = Math.max(1, rect.width);
      state.height = Math.max(1, rect.height);
      state.dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(state.width * state.dpr);
      canvas.height = Math.round(state.height * state.dpr);
      canvas.style.width = `${state.width}px`;
      canvas.style.height = `${state.height}px`;
      fitView();
    }

    function drawEdge(edge, source, target, highlighted) {
      const color = edgeColors[edge.type];
      ctx.beginPath();
      ctx.moveTo(source.x, source.y);
      ctx.lineTo(target.x, target.y);
      ctx.strokeStyle = color;
      ctx.globalAlpha = highlighted ? .95 : edgeAlpha[edge.type] ?? .2;
      ctx.lineWidth = (highlighted ? 2.4 : edgeWidth[edge.type] ?? .8) / state.view.k;
      ctx.setLineDash(
        edge.type === "qualifiedMapping" ? [7 / state.view.k, 5 / state.view.k]
        : edge.type === "use" ? [2 / state.view.k, 4 / state.view.k]
        : edge.type === "rejectedCandidate" ? [3 / state.view.k, 3 / state.view.k]
        : []
      );
      ctx.stroke();
      ctx.setLineDash([]);
      if (edge.type === "broader" && highlighted) {
        const angle = Math.atan2(target.y - source.y, target.x - source.x);
        const size = 5 / state.view.k;
        ctx.beginPath();
        ctx.moveTo(target.x, target.y);
        ctx.lineTo(target.x - Math.cos(angle - .45) * size, target.y - Math.sin(angle - .45) * size);
        ctx.lineTo(target.x - Math.cos(angle + .45) * size, target.y - Math.sin(angle + .45) * size);
        ctx.closePath();
        ctx.fillStyle = color;
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    function drawLabel(node, radius) {
      const release = releaseById.get(node.releaseId);
      ctx.font = `${11 / state.view.k}px ui-sans-serif, system-ui, sans-serif`;
      ctx.textBaseline = "middle";
      const textWidth = ctx.measureText(node.label).width;
      const x = node.x + radius + 5 / state.view.k;
      const y = node.y;
      ctx.fillStyle = "rgba(8, 13, 12, .9)";
      ctx.fillRect(x - 2 / state.view.k, y - 8 / state.view.k, textWidth + 5 / state.view.k, 16 / state.view.k);
      ctx.fillStyle = release ? release.color : "#edf1ed";
      ctx.fillText(node.label, x, y);
    }

    function draw() {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.setTransform(
        state.dpr * state.view.k, 0, 0, state.dpr * state.view.k,
        state.dpr * state.view.x, state.dpr * state.view.y
      );

      data.edges.forEach(edge => {
        if (!isEdgeVisible(edge)) return;
        const source = nodeById.get(edge.source);
        const target = nodeById.get(edge.target);
        const highlighted = state.selected && (edge.source === state.selected || edge.target === state.selected);
        drawEdge(edge, source, target, highlighted);
      });

      data.nodes.forEach(row => {
        const node = nodeById.get(row.id);
        if (!isNodeVisible(node)) return;
        const release = releaseById.get(node.releaseId);
        const radius = nodeRadius(node) / state.view.k;
        const selected = state.selected === node.id;
        const hovered = state.hover === node.id;
        const searchDimmed = state.query && !state.matches.has(node.id) && !selected;
        ctx.globalAlpha = searchDimmed ? .14 : 1;
        if (node.roles.includes("mappingEndpoint")) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, radius + 3 / state.view.k, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(233, 185, 95, .42)";
          ctx.lineWidth = 1 / state.view.k;
          ctx.stroke();
        }
        if (selected || hovered) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, radius + 5 / state.view.k, 0, Math.PI * 2);
          ctx.fillStyle = selected ? "rgba(233, 185, 95, .2)" : "rgba(140, 211, 199, .15)";
          ctx.fill();
        }
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
        if (node.deprecated) {
          // Retired concepts are hollow: the release colour survives as an
          // outline so the succession edge reads as "this one ended".
          ctx.fillStyle = "#0c1211";
          ctx.fill();
          ctx.strokeStyle = release ? release.color : "#edf1ed";
          ctx.lineWidth = (selected ? 2 : 1.4) / state.view.k;
          ctx.stroke();
        } else {
          ctx.fillStyle = release ? release.color : "#edf1ed";
          ctx.fill();
          ctx.strokeStyle = selected ? "#fff3d9" : "rgba(7, 12, 11, .8)";
          ctx.lineWidth = (selected ? 2 : 1) / state.view.k;
          ctx.stroke();
        }
        ctx.globalAlpha = 1;
        if (selected || hovered || (state.matches.has(node.id) && state.matches.size <= 12)) drawLabel(node, radius);
      });
    }

    function hitTest(clientX, clientY) {
      const rect = canvas.getBoundingClientRect();
      const point = screenToWorld(clientX - rect.left, clientY - rect.top);
      let found = null;
      let distance = Infinity;
      data.nodes.forEach(row => {
        const node = nodeById.get(row.id);
        if (!isNodeVisible(node)) return;
        const dx = node.x - point.x;
        const dy = node.y - point.y;
        const candidate = Math.hypot(dx, dy);
        const threshold = nodeRadius(node) / state.view.k + 8 / state.view.k;
        if (candidate <= threshold && candidate < distance) {
          found = node;
          distance = candidate;
        }
      });
      return found;
    }

    function zoomAt(factor, x = state.width / 2, y = state.height / 2) {
      const before = screenToWorld(x, y);
      state.view.k = Math.max(.15, Math.min(8, state.view.k * factor));
      state.view.x = x - before.x * state.view.k;
      state.view.y = y - before.y * state.view.k;
      draw();
    }

    function focusNode(node) {
      const targetScale = Math.max(1.1, Math.min(2.8, state.view.k));
      const target = {
        k: targetScale,
        x: state.width / 2 - node.x * targetScale,
        y: state.height / 2 - node.y * targetScale
      };
      if (reducedMotion) {
        state.view = target;
        draw();
        return;
      }
      const start = { ...state.view };
      const started = performance.now();
      function frame(now) {
        const progress = Math.min(1, (now - started) / 280);
        const eased = 1 - Math.pow(1 - progress, 3);
        state.view.k = start.k + (target.k - start.k) * eased;
        state.view.x = start.x + (target.x - start.x) * eased;
        state.view.y = start.y + (target.y - start.y) * eased;
        draw();
        if (progress < 1) requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    }

    function roleLabel(node) {
      let base = "Hierarchy context";
      if (node.roles.includes("mappingEndpoint")) base = "Qualified mapping endpoint";
      else if (node.roles.includes("sharedLabel")) base = "Cross-release shared label";
      else if (node.roles.includes("lifecycle")) base = "Lifecycle record";
      else if (node.roles.includes("releaseRepresentative")) base = "Reference release sample";
      const badges = [];
      if (node.deprecated) badges.push("deprecated");
      if (node.roles.includes("topConcept")) badges.push("top concept");
      return badges.length ? `${base} · ${badges.join(" · ")}` : base;
    }

    function selectNode(node, move = false) {
      state.selected = node ? node.id : null;
      if (node && !state.activeReleases.has(node.releaseId)) state.activeReleases.add(node.releaseId);
      renderInspector();
      draw();
      if (node && move) focusNode(node);
    }

    function renderInspector() {
      const empty = document.getElementById("empty-inspector");
      const content = document.getElementById("inspector-content");
      const inspector = document.getElementById("inspector");
      const node = state.selected ? nodeById.get(state.selected) : null;
      empty.hidden = Boolean(node);
      content.hidden = !node;
      inspector.classList.toggle("open", Boolean(node));
      if (!node) return;
      const release = releaseById.get(node.releaseId);
      const links = adjacency.get(node.id).filter(item => isEdgeVisible(item.edge));
      document.getElementById("node-role").textContent = roleLabel(node);
      document.getElementById("node-title").textContent = node.label;
      document.getElementById("node-release").textContent = release.label;
      document.getElementById("node-swatch").style.setProperty("--node-color", release.color);
      const iri = document.getElementById("node-iri");
      iri.textContent = node.id;
      if (/^https?:/.test(node.id)) {
        iri.href = node.id;
        iri.target = "_blank";
        iri.rel = "noreferrer";
      } else {
        iri.removeAttribute("href");
        iri.removeAttribute("target");
      }
      document.getElementById("node-link-count").textContent = formatNumber(links.length);
      const notation = document.getElementById("notation-value");
      document.getElementById("notation-term").hidden = notation.hidden = !node.notation;
      notation.textContent = node.notation || "";
      const definition = document.getElementById("node-definition");
      definition.hidden = !node.definition;
      definition.textContent = node.definition ? `Definition — ${node.definition}` : "";
      const scopeNote = document.getElementById("node-scope-note");
      scopeNote.hidden = !node.scopeNote;
      scopeNote.textContent = node.scopeNote ? `Scope note — ${node.scopeNote}` : "";
      document.getElementById("node-notes").hidden = !(node.definition || node.scopeNote);
      const container = document.getElementById("connections");
      container.replaceChildren();
      links
        .sort((a, b) => a.edge.type.localeCompare(b.edge.type) || nodeById.get(a.other).label.localeCompare(nodeById.get(b.other).label))
        .forEach(item => {
          const other = nodeById.get(item.other);
          const button = document.createElement("button");
          button.type = "button";
          button.className = "connection";
          button.style.setProperty("--connection-color", edgeColors[item.edge.type]);
          const name = document.createElement("b");
          name.textContent = other.label;
          const relation = document.createElement("small");
          const detail = item.edge.type === "qualifiedMapping" ? item.edge.label : edgeLabels[item.edge.type];
          relation.textContent = `${detail} · ${releaseById.get(other.releaseId).label}`;
          button.append(name, relation);
          button.addEventListener("click", () => selectNode(other, true));
          const reasons = item.edge.reasons || [];
          if (!reasons.length) {
            container.append(button);
            return;
          }
          // Only the two decision edge types carry reasons, so this is the
          // gate's own words about this pair — shown under the relationship
          // rather than behind another click.
          const group = document.createElement("div");
          group.className = "connection-group";
          group.append(button);
          reasons.forEach(entry => {
            const note = document.createElement("p");
            note.className = "connection-reason";
            const who = document.createElement("b");
            who.textContent = `${entry.label} — `;
            note.append(who, document.createTextNode(entry.reason));
            group.append(note);
          });
          container.append(group);
        });
    }

    function renderSearch() {
      const query = search.value.trim().toLocaleLowerCase();
      state.query = query;
      const matching = query
        ? data.nodes.filter(node => node.label.toLocaleLowerCase().includes(query) || node.id.toLocaleLowerCase().includes(query))
        : [];
      state.matches = new Set(matching.map(node => node.id));
      resultBox.replaceChildren();
      matching.slice(0, 8).forEach(row => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "result";
        const label = document.createElement("span");
        label.textContent = row.label;
        const source = document.createElement("small");
        source.textContent = releaseById.get(row.releaseId).label;
        button.append(label, source);
        button.addEventListener("click", () => selectNode(nodeById.get(row.id), true));
        resultBox.append(button);
      });
      if (query && !matching.length) {
        const note = document.createElement("small");
        note.textContent = "No concept in this bounded view.";
        resultBox.append(note);
      }
      draw();
    }

    function renderFilters() {
      data.releases.forEach(release => {
        const meta = releaseById.get(release.id);
        const label = document.createElement("label");
        label.className = "filter release-filter";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = true;
        input.dataset.release = release.id;
        const swatch = document.createElement("span");
        swatch.className = "swatch";
        swatch.style.setProperty("--swatch", meta.color);
        const text = document.createElement("span");
        text.className = "label";
        text.textContent = release.label;
        const count = document.createElement("small");
        count.textContent = formatNumber(release.shownNodeCount);
        label.append(input, swatch, text, count);
        releaseFilters.append(label);
        input.addEventListener("change", () => {
          if (input.checked) state.activeReleases.add(release.id);
          else state.activeReleases.delete(release.id);
          if (state.selected && !isNodeVisible(nodeById.get(state.selected))) selectNode(null);
          fitView();
        });
      });
      document.querySelectorAll("[data-edge]").forEach(input => {
        input.addEventListener("change", () => {
          if (input.checked) state.activeEdges.add(input.dataset.edge);
          else state.activeEdges.delete(input.dataset.edge);
          renderInspector();
          draw();
        });
      });
    }

    function populateText() {
      document.getElementById("short-id").textContent = shortId(data.atlas.assetId);
      document.getElementById("metric-sources").textContent = formatNumber(data.atlas.counts.managedReleases);
      document.getElementById("metric-quads").textContent = formatNumber(data.atlas.quadCount);
      document.getElementById("metric-mappings").textContent = formatNumber(data.atlas.counts.searchOnlyMappings);
      document.getElementById("count-qualified").textContent = `${formatNumber(data.summary.qualifiedMappingCount)} shown`;
      document.getElementById("count-shared").textContent = `${formatNumber(data.summary.sharedLabelEdgeCount)} shown`;
      document.getElementById("count-broader").textContent = `${formatNumber(data.summary.hierarchyEdgeCount)} shown`;
      document.getElementById("count-related").textContent = `${formatNumber(data.summary.relatedEdgeCount)} shown`;
      document.getElementById("count-use").textContent = `${formatNumber(data.summary.useEdgeCount)} shown`;
      document.getElementById("count-replaced").textContent = `${formatNumber(data.summary.replacedByEdgeCount)} shown`;
      document.getElementById("count-rejected").textContent = `${formatNumber(data.summary.rejectedCandidateEdgeCount)} available`;
      document.getElementById("selection-note").textContent = `${formatNumber(data.summary.nodeCount)} concepts and ${formatNumber(data.summary.edgeCount)} relationships are shown. The complete atlas remains in the download.`;
      document.getElementById("view-count").textContent = `${formatNumber(data.summary.nodeCount)} nodes · ${formatNumber(data.summary.edgeCount)} links`;
      document.getElementById("pin-id").textContent = data.atlas.assetId;
      document.getElementById("pin-manifest").textContent = data.atlas.manifestDigest;
      document.getElementById("pin-output").textContent = data.atlas.distributionDigest;
      document.getElementById("pin-selection").textContent = data.selectionPolicy.id;
    }

    canvas.addEventListener("pointerdown", event => {
      canvas.setPointerCapture(event.pointerId);
      const hit = hitTest(event.clientX, event.clientY);
      state.lastPointer = { x: event.clientX, y: event.clientY };
      if (hit) {
        selectNode(hit);
      } else {
        state.panning = true;
        state.dragStart = { x: event.clientX, y: event.clientY, viewX: state.view.x, viewY: state.view.y };
        canvas.classList.add("panning");
      }
    });
    canvas.addEventListener("pointermove", event => {
      state.lastPointer = { x: event.clientX, y: event.clientY };
      if (state.panning && state.dragStart) {
        state.view.x = state.dragStart.viewX + event.clientX - state.dragStart.x;
        state.view.y = state.dragStart.viewY + event.clientY - state.dragStart.y;
        draw();
        return;
      }
      const hit = hitTest(event.clientX, event.clientY);
      state.hover = hit ? hit.id : null;
      if (hit) {
        const rect = stage.getBoundingClientRect();
        tooltip.replaceChildren();
        const name = document.createTextNode(hit.label);
        const source = document.createElement("small");
        source.textContent = releaseById.get(hit.releaseId).label;
        tooltip.append(name, source);
        tooltip.style.left = `${event.clientX - rect.left}px`;
        tooltip.style.top = `${event.clientY - rect.top}px`;
        tooltip.hidden = false;
      } else {
        tooltip.hidden = true;
      }
      draw();
    });
    canvas.addEventListener("pointerup", event => {
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      state.panning = false;
      state.dragStart = null;
      canvas.classList.remove("panning");
    });
    canvas.addEventListener("pointerleave", () => {
      state.hover = null;
      tooltip.hidden = true;
      draw();
    });
    canvas.addEventListener("wheel", event => {
      event.preventDefault();
      const rect = canvas.getBoundingClientRect();
      zoomAt(event.deltaY < 0 ? 1.12 : .89, event.clientX - rect.left, event.clientY - rect.top);
    }, { passive: false });
    canvas.addEventListener("keydown", event => {
      const step = 32;
      if (event.key === "+" || event.key === "=") zoomAt(1.2);
      else if (event.key === "-") zoomAt(.83);
      else if (event.key === "ArrowLeft") state.view.x += step;
      else if (event.key === "ArrowRight") state.view.x -= step;
      else if (event.key === "ArrowUp") state.view.y += step;
      else if (event.key === "ArrowDown") state.view.y -= step;
      else return;
      event.preventDefault();
      draw();
    });
    document.getElementById("zoom-in").addEventListener("click", () => zoomAt(1.25));
    document.getElementById("zoom-out").addEventListener("click", () => zoomAt(.8));
    document.getElementById("fit-view").addEventListener("click", fitView);
    document.getElementById("toggle-controls").addEventListener("click", event => {
      const controls = document.getElementById("controls");
      controls.classList.toggle("open");
      event.currentTarget.setAttribute("aria-label", controls.classList.contains("open") ? "Hide filters" : "Show filters");
    });
    document.getElementById("copy-iri").addEventListener("click", async event => {
      if (!state.selected) return;
      try {
        await navigator.clipboard.writeText(state.selected);
        event.currentTarget.textContent = "Copied";
        window.setTimeout(() => { event.currentTarget.textContent = "Copy IRI"; }, 1200);
      } catch (_) {
        event.currentTarget.textContent = "Copy unavailable";
      }
    });
    search.addEventListener("input", renderSearch);
    window.addEventListener("keydown", event => {
      if (event.key === "/" && document.activeElement !== search) {
        event.preventDefault();
        search.focus();
      }
      if (event.key === "Escape") {
        search.value = "";
        renderSearch();
        selectNode(null);
      }
    });
    new ResizeObserver(resize).observe(stage);

    layout();
    populateText();
    renderFilters();
    resize();
    requestAnimationFrame(() => canvas.classList.add("ready"));
  })();
  </script>
</body>
</html>
"""


def _safe_json(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def render_atlas_explorer(model: Mapping[str, Any]) -> str:
    """Return one self-contained HTML file for a bounded atlas view."""

    title = str(model.get("title") or "RefSpec vocabulary atlas")
    return _Template(_HTML).substitute(
        title=html.escape(title, quote=True),
        atlas_data=_safe_json(model),
    )


__all__ = ["render_atlas_explorer"]
