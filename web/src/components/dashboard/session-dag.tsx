"use client";

import { useRef, useEffect, useState, useCallback, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import gsap from "gsap";

// ── Types ─────────────────────────────────────────────────

interface DagNode {
  id: number;
  action_type: string;
  action_detail: string;
  status: "effective" | "reverted" | "waste";
  error?: boolean;
  parent_ids: number[];
  trace_id: string | null;
  files_touched: string[];
  latency_ms: number;
  reverted_by: number | null;
}

interface DagEdge {
  source: number;
  target: number;
  type: "causal" | "cross_trace";
}

interface DagData {
  nodes: DagNode[];
  edges: DagEdge[];
  critical_path?: number[];
  stats: {
    total_nodes: number;
    effective_nodes: number;
    reverted_nodes: number;
    waste_nodes: number;
  };
}

type ViewMode = "graph" | "timeline";

// ── Shared constants ──────────────────────────────────────

const STATUS_COLORS: Record<string, { fill: string; stroke: string; glow: string }> = {
  effective: { fill: "#10b981", stroke: "#6ee7b7", glow: "rgba(16,185,129,0.5)" },
  reverted:  { fill: "#ef4444", stroke: "#fca5a5", glow: "rgba(239,68,68,0.5)" },
  waste:     { fill: "#f59e0b", stroke: "#fde68a", glow: "rgba(245,158,11,0.5)" },
  error:     { fill: "#dc2626", stroke: "#f87171", glow: "rgba(220,38,38,0.6)" },
};

const CRITICAL_PATH_COLOR = "#e879f9";
const CRITICAL_PATH_GLOW = "rgba(232,121,249,0.4)";

const ACTION_LETTER: Record<string, string> = {
  file_read: "R", file_write: "W", file_delete: "D",
  bash: "B", search: "S", think: "T", mcp_meta: "M",
};

const ACTION_WORD: Record<string, string> = {
  file_read: "Read", file_write: "Write", file_delete: "Delete",
  bash: "Bash", search: "Search", think: "Think", mcp_meta: "MCP",
};

const ACTION_COLOR: Record<string, string> = {
  file_read: "#60a5fa", file_write: "#a78bfa", file_delete: "#f87171",
  bash: "#34d399", search: "#fbbf24", think: "#94a3b8", mcp_meta: "#e879f9",
};

// ── Shared helpers ────────────────────────────────────────

function parseDetail(detail: string): string {
  if (!detail) return "";
  try {
    const p = JSON.parse(detail);
    if (p && typeof p === "object") return p.command || p.file_path || p.path || p.pattern || detail;
  } catch { /* */ }
  return detail;
}

function truncate(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, n) + "…";
}

function formatLatency(ms: number): string {
  if (ms <= 0) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function getNodeVisualStatus(node: DagNode): string {
  if (node.error) return "error";
  return node.status;
}

// ── Shared stat pills ─────────────────────────────────────

function StatPills({ stats, crossCount, errorCount }: { stats: DagData["stats"]; crossCount: number; errorCount: number }) {
  return (
    <div className="flex items-center gap-1.5">
      {[
        { l: "effective", c: stats.effective_nodes, color: "#10b981", textColor: "var(--color-success)" },
        { l: "reverted", c: stats.reverted_nodes, color: "#ef4444", textColor: "var(--color-destructive)" },
        { l: "waste", c: stats.waste_nodes, color: "#f59e0b", textColor: "var(--color-warning)" },
      ].map(({ l, c, color, textColor }) => (
        <div key={l} className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium"
          style={{ background: color + "0d", border: `1px solid ${color}25`, color: textColor }}>
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />{c}
        </div>
      ))}
      {errorCount > 0 && (
        <div className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium"
          style={{ background: "color-mix(in oklch, var(--color-destructive) 8%, transparent)", border: "1px solid color-mix(in oklch, var(--color-destructive) 20%, transparent)", color: "var(--color-destructive)" }}>
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--color-destructive)" }} />{errorCount} err
        </div>
      )}
      <div className="px-2 py-0.5 rounded-full text-[10px] text-muted-foreground"
        style={{ background: "color-mix(in oklch, var(--color-muted-foreground) 8%, transparent)", border: "1px solid var(--color-border)" }}>
        {stats.total_nodes}
      </div>
      {crossCount > 0 && (
        <div className="px-2 py-0.5 rounded-full text-[10px] font-medium"
          style={{ background: "color-mix(in oklch, var(--color-info) 8%, transparent)", border: "1px solid color-mix(in oklch, var(--color-info) 20%, transparent)", color: "var(--color-info)" }}>
          {crossCount} cross
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// GRAPH VIEW (force-directed, Obsidian style)
// ═══════════════════════════════════════════════════════════

const NODE_R = 6;
const HOVER_R = 9;

interface SimNode { id: number; x: number; y: number; vx: number; vy: number; node: DagNode }

function forceLayout(nodes: DagNode[], edges: DagEdge[], w: number, h: number): Map<number, { x: number; y: number }> {
  if (!nodes.length) return new Map();

  const sim: SimNode[] = nodes.map((n, i) => {
    const angle = (i / nodes.length) * Math.PI * 2;
    const radius = Math.min(w, h) * 0.3;
    return { id: n.id, x: w / 2 + Math.cos(angle) * radius * (0.5 + Math.random() * 0.5), y: h / 2 + Math.sin(angle) * radius * (0.5 + Math.random() * 0.5), vx: 0, vy: 0, node: n };
  });

  const idx = new Map<number, number>();
  sim.forEach((s, i) => idx.set(s.id, i));
  const edgeLinks = edges.filter(e => idx.has(e.source) && idx.has(e.target)).map(e => ({ si: idx.get(e.source)!, ti: idx.get(e.target)!, type: e.type }));

  for (let iter = 0; iter < 300; iter++) {
    const temp = 1 - iter / 300;
    for (let i = 0; i < sim.length; i++) {
      for (let j = i + 1; j < sim.length; j++) {
        const dx = sim[j].x - sim[i].x;
        const dy = sim[j].y - sim[i].y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = (1200 * temp) / (dist * dist);
        const fx = (dx / dist) * force; const fy = (dy / dist) * force;
        sim[i].vx -= fx; sim[i].vy -= fy; sim[j].vx += fx; sim[j].vy += fy;
      }
    }
    for (const link of edgeLinks) {
      const a = sim[link.si]; const b = sim[link.ti];
      const dx = b.x - a.x; const dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const k = link.type === "cross_trace" ? 0.003 : 0.008;
      const force = k * dist * temp;
      const fx = (dx / dist) * force; const fy = (dy / dist) * force;
      a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
    }
    for (const s of sim) {
      s.vx += (w / 2 - s.x) * 0.01 * temp; s.vy += (h / 2 - s.y) * 0.01 * temp;
      s.vx *= 0.85; s.vy *= 0.85;
      s.x += s.vx; s.y += s.vy;
      s.x = Math.max(40, Math.min(w - 40, s.x)); s.y = Math.max(40, Math.min(h - 40, s.y));
    }
  }

  const result = new Map<number, { x: number; y: number }>();
  for (const s of sim) result.set(s.id, { x: s.x, y: s.y });
  return result;
}

function GraphHoverCard({ node, screenX, screenY, containerW }: { node: DagNode; screenX: number; screenY: number; containerW: number }) {
  const vs = getNodeVisualStatus(node);
  const s = STATUS_COLORS[vs] || STATUS_COLORS.effective;
  const detail = parseDetail(node.action_detail);
  const accent = ACTION_COLOR[node.action_type] || "#94a3b8";
  const cardW = 270;
  const flipLeft = screenX + cardW + 24 > containerW;
  return (
    <div className="absolute pointer-events-none z-50" style={{ left: flipLeft ? screenX - cardW - 16 : screenX + 20, top: screenY - 50, width: cardW }}>
      <div className="rounded-xl border backdrop-blur-xl overflow-hidden" style={{ background: "var(--color-popover)", borderColor: s.stroke + "50", boxShadow: `0 0 30px ${s.glow}, 0 16px 40px rgba(0,0,0,0.5)` }}>
        <div className="px-3 py-2 flex items-center gap-2" style={{ borderBottom: `1px solid ${s.stroke}25` }}>
          <div className="w-5 h-5 rounded-full flex items-center justify-center text-[8px] font-black" style={{ background: accent + "22", color: accent, border: `1.5px solid ${accent}55` }}>{ACTION_LETTER[node.action_type] || "?"}</div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5"><span className="font-semibold text-[11px] text-popover-foreground">{ACTION_WORD[node.action_type] || node.action_type}</span><span className="text-[8px] font-mono text-muted-foreground">#{node.id}</span></div>
            {detail && <span className="text-[9px] font-mono text-muted-foreground block truncate">{truncate(detail, 45)}</span>}
          </div>
          <div className="flex items-center gap-1">
            <div className="px-1.5 py-0.5 rounded text-[7px] font-bold uppercase tracking-wider" style={{ background: s.fill + "18", color: s.stroke, border: `1px solid ${s.stroke}35` }}>{node.status}</div>
            {node.error && (
              <div className="px-1.5 py-0.5 rounded text-[7px] font-bold uppercase tracking-wider" style={{ background: "color-mix(in oklch, var(--color-destructive) 15%, transparent)", color: "var(--color-destructive)", border: "1px solid color-mix(in oklch, var(--color-destructive) 30%, transparent)" }}>FAIL</div>
            )}
          </div>
        </div>
        <div className="px-3 py-2 space-y-1.5">
          {node.error && (
            <div className="rounded px-2 py-1 text-[9px] text-destructive flex items-center gap-1.5" style={{ background: "color-mix(in oklch, var(--color-destructive) 8%, transparent)", border: "1px solid color-mix(in oklch, var(--color-destructive) 15%, transparent)" }}>
              <span className="w-3 h-3 rounded-full flex items-center justify-center text-[7px] font-black shrink-0" style={{ background: "color-mix(in oklch, var(--color-destructive) 20%, transparent)", color: "var(--color-destructive)" }}>!</span>
              Tool call failed
            </div>
          )}
          {node.files_touched.length > 0 && <div><span className="text-[8px] font-semibold uppercase tracking-wider text-muted-foreground block mb-0.5">Files</span>{node.files_touched.slice(0, 3).map((f, i) => <div key={i} className="text-[9px] font-mono text-popover-foreground truncate pl-1.5" style={{ borderLeft: `2px solid ${accent}35` }}>{f.split(/[/\\]/).pop() || f}</div>)}</div>}
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {node.latency_ms > 0 && <div><span className="text-[8px] text-muted-foreground block">Latency</span><span className="text-[9px] font-mono text-popover-foreground">{formatLatency(node.latency_ms)}</span></div>}
            {node.trace_id && <div><span className="text-[8px] text-muted-foreground block">Trace</span><span className="text-[9px] font-mono text-info">{node.trace_id.slice(0, 10)}</span></div>}
            {node.parent_ids.length > 0 && <div><span className="text-[8px] text-muted-foreground block">Parents</span><span className="text-[9px] font-mono text-popover-foreground">{node.parent_ids.map(p => `#${p}`).join(", ")}</span></div>}
            {node.reverted_by !== null && <div><span className="text-[8px] text-muted-foreground block">Reverted by</span><span className="text-[9px] font-mono text-destructive">#{node.reverted_by}</span></div>}
          </div>
          {node.status === "reverted" && <div className="rounded px-2 py-1 text-[9px] text-destructive" style={{ background: "color-mix(in oklch, var(--color-destructive) 6%, transparent)", border: "1px solid color-mix(in oklch, var(--color-destructive) 12%, transparent)" }}>Reverted{node.reverted_by !== null ? ` by #${node.reverted_by}` : ""}</div>}
          {node.status === "waste" && <div className="rounded px-2 py-1 text-[9px] text-warning" style={{ background: "color-mix(in oklch, var(--color-warning) 6%, transparent)", border: "1px solid color-mix(in oklch, var(--color-warning) 12%, transparent)" }}>Did not contribute to final state</div>}
        </div>
      </div>
    </div>
  );
}

function GraphView({ dag, criticalSet, criticalEdgeSet }: { dag: DagData; criticalSet: Set<number>; criticalEdgeSet: Set<string> }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [containerWidth, setContainerWidth] = useState(800);
  const [hoveredNode, setHoveredNode] = useState<number | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const panStart = useRef({ x: 0, y: 0, px: 0, py: 0 });
  const animatedRef = useRef(false);
  const canvasW = 900; const canvasH = 600;

  const positions = useMemo(() => forceLayout(dag.nodes, dag.edges, canvasW, canvasH), [dag.nodes, dag.edges]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setContainerWidth(entry.contentRect.width));
    ro.observe(el);
    setContainerWidth(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    function onWheel(e: WheelEvent) {
      e.preventDefault(); e.stopPropagation();
      const rect = el!.getBoundingClientRect();
      const mx = e.clientX - rect.left; const my = e.clientY - rect.top;
      const factor = e.deltaY > 0 ? 0.92 : 1.08;
      setZoom(prev => { const next = Math.max(0.15, Math.min(10, prev * factor)); const scale = next / prev; setPan(p => ({ x: mx - (mx - p.x) * scale, y: my - (my - p.y) * scale })); return next; });
    }
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  useEffect(() => {
    if (!containerRef.current || !positions.size) return;
    const rect = containerRef.current.getBoundingClientRect();
    const fit = Math.max(0.15, Math.min((rect.width - 40) / canvasW, (rect.height - 40) / canvasH, 1.2));
    setZoom(fit); setPan({ x: (rect.width - canvasW * fit) / 2, y: (rect.height - canvasH * fit) / 2 });
  }, [positions]);

  useEffect(() => {
    if (animatedRef.current || !svgRef.current || !positions.size) return;
    animatedRef.current = true;
    const circles = svgRef.current.querySelectorAll("[data-nc]");
    const paths = svgRef.current.querySelectorAll("[data-ep]");
    gsap.set(circles, { scale: 0, transformOrigin: "center" });
    gsap.set(paths, { opacity: 0, strokeDashoffset: 400, strokeDasharray: 400 });
    const tl = gsap.timeline();
    tl.to(circles, { scale: 1, duration: 0.5, ease: "elastic.out(1,0.6)", stagger: { each: 0.008 } });
    tl.to(paths, { opacity: 1, strokeDashoffset: 0, duration: 0.7, ease: "expo.out", stagger: 0.005 }, "-=0.3");
  }, [positions]);

  const onPointerDown = useCallback((e: React.PointerEvent) => { if (e.button !== 0) return; setIsPanning(true); panStart.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y }; (e.target as HTMLElement).setPointerCapture?.(e.pointerId); }, [pan]);
  const onPointerMove = useCallback((e: React.PointerEvent) => { if (!isPanning) return; setPan({ x: panStart.current.px + (e.clientX - panStart.current.x), y: panStart.current.py + (e.clientY - panStart.current.y) }); }, [isPanning]);
  const onPointerUp = useCallback(() => setIsPanning(false), []);

  const hoveredData = useMemo(() => hoveredNode !== null ? dag.nodes.find(n => n.id === hoveredNode) || null : null, [hoveredNode, dag.nodes]);
  const hoveredScreenPos = useMemo(() => { if (hoveredNode === null) return null; const p = positions.get(hoveredNode); return p ? { x: p.x * zoom + pan.x, y: p.y * zoom + pan.y } : null; }, [hoveredNode, positions, zoom, pan]);

  return (
    <div
      ref={containerRef}
      className="relative rounded-xl select-none"
      style={{ height: 520, background: "radial-gradient(ellipse at center, var(--color-surface-sunken) 0%, var(--color-background) 100%)", border: "1px solid var(--color-border)", cursor: isPanning ? "grabbing" : "grab", overflow: "hidden", touchAction: "none" }}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerLeave={onPointerUp}
    >
      <div className="absolute inset-0 pointer-events-none" style={{ backgroundImage: "radial-gradient(color-mix(in oklch, var(--color-muted-foreground) 8%, transparent) 1px, transparent 1px)", backgroundSize: `${24 * zoom}px ${24 * zoom}px`, backgroundPosition: `${pan.x % (24 * zoom)}px ${pan.y % (24 * zoom)}px` }} />
      <svg ref={svgRef} className="absolute inset-0 w-full h-full" style={{ overflow: "visible" }}>
        <defs>
          <marker id="ac" viewBox="0 0 6 4" refX="5" refY="2" markerWidth="5" markerHeight="4" orient="auto-start-reverse"><path d="M0 0L6 2L0 4z" fill="rgba(100,116,139,0.25)" /></marker>
          <marker id="ax" viewBox="0 0 6 4" refX="5" refY="2" markerWidth="5" markerHeight="4" orient="auto-start-reverse"><path d="M0 0L6 2L0 4z" fill="rgba(59,130,246,0.45)" /></marker>
          <marker id="ah" viewBox="0 0 6 4" refX="5" refY="2" markerWidth="5" markerHeight="4" orient="auto-start-reverse"><path d="M0 0L6 2L0 4z" fill="rgba(200,210,220,0.6)" /></marker>
          <marker id="acp" viewBox="0 0 6 4" refX="5" refY="2" markerWidth="5" markerHeight="4" orient="auto-start-reverse"><path d="M0 0L6 2L0 4z" fill={CRITICAL_PATH_COLOR} fillOpacity="0.7" /></marker>
        </defs>
        <g transform={`translate(${pan.x},${pan.y}) scale(${zoom})`}>
          {dag.edges.map((edge, i) => {
            const sp = positions.get(edge.source); const tp = positions.get(edge.target);
            if (!sp || !tp) return null;
            const isCross = edge.type === "cross_trace";
            const isCritical = criticalEdgeSet.has(`${edge.source}-${edge.target}`);
            const isLit = hoveredNode !== null && (edge.source === hoveredNode || edge.target === hoveredNode);
            const isDim = hoveredNode !== null && !isLit;
            const dx = tp.x - sp.x; const dy = tp.y - sp.y; const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            const shrink = NODE_R + 2;
            const sx = sp.x + (dx / dist) * shrink; const sy = sp.y + (dy / dist) * shrink;
            const tx = tp.x - (dx / dist) * shrink; const ty = tp.y - (dy / dist) * shrink;
            const mx = (sx + tx) / 2; const my = (sy + ty) / 2;
            const nx = -(ty - sy); const ny = tx - sx;
            const bend = isCross ? 0.15 : 0.05;

            let stroke = isCross ? "color-mix(in oklch, var(--color-info) 30%, transparent)" : "color-mix(in oklch, var(--color-border) 50%, transparent)";
            let strokeW = isCross ? 0.9 : 0.6;
            let marker = isCross ? "url(#ax)" : "url(#ac)";

            if (isCritical && !isLit) {
              stroke = CRITICAL_PATH_COLOR + "88";
              strokeW = 1.4;
              marker = "url(#acp)";
            }
            if (isLit) {
              stroke = "rgba(200,210,220,0.55)";
              strokeW = 1.2;
              marker = "url(#ah)";
            }

            return <path key={`e${i}`} data-ep d={`M${sx} ${sy} Q${mx + nx * bend} ${my + ny * bend} ${tx} ${ty}`} fill="none" stroke={stroke} strokeWidth={strokeW} strokeDasharray={isCross ? "3 2.5" : "none"} markerEnd={marker} opacity={isDim ? 0.06 : 1} style={{ transition: "opacity 0.15s, stroke 0.15s" }} />;
          })}
          {dag.nodes.map(node => {
            const p = positions.get(node.id); if (!p) return null;
            const vs = getNodeVisualStatus(node);
            const s = STATUS_COLORS[vs] || STATUS_COLORS.effective;
            const isCrit = criticalSet.has(node.id);
            const isH = hoveredNode === node.id;
            const isConn = hoveredNode !== null && dag.edges.some(e => (e.source === hoveredNode && e.target === node.id) || (e.target === hoveredNode && e.source === node.id));
            const isDim = hoveredNode !== null && !isH && !isConn;

            const nodeStroke = isCrit && !isH ? CRITICAL_PATH_COLOR : s.stroke;
            const nodeGlow = isCrit && !isH ? CRITICAL_PATH_GLOW : s.glow;

            return (
              <g key={`n${node.id}`} style={{ opacity: isDim ? 0.15 : 1, transition: "opacity 0.15s", cursor: "pointer" }} onMouseEnter={() => setHoveredNode(node.id)} onMouseLeave={() => setHoveredNode(null)}>
                <circle cx={p.x} cy={p.y} r={isH ? 18 : isCrit ? 14 : 12} fill={nodeGlow} opacity={isH ? 0.35 : isCrit ? 0.2 : 0.08} />
                {isH && <circle cx={p.x} cy={p.y} r={HOVER_R + 3} fill="none" stroke={nodeStroke} strokeWidth={1} opacity={0.5} />}
                {isCrit && !isH && <circle cx={p.x} cy={p.y} r={NODE_R + 2.5} fill="none" stroke={CRITICAL_PATH_COLOR} strokeWidth={0.6} opacity={0.4} strokeDasharray="2 1.5" />}
                <circle data-nc cx={p.x} cy={p.y} r={isH ? HOVER_R : NODE_R} fill={s.fill} stroke={nodeStroke} strokeWidth={isH ? 1.8 : isCrit ? 1.4 : 1} style={{ transition: "r 0.1s" }} />
                {node.error && <text x={p.x} y={p.y + 0.3} textAnchor="middle" dominantBaseline="central" fill="white" fontSize={isH ? 8 : 6} fontWeight={900} fontFamily="monospace" style={{ pointerEvents: "none", userSelect: "none" }}>!</text>}
                {!node.error && zoom >= 1.0 && <text x={p.x} y={p.y + 0.3} textAnchor="middle" dominantBaseline="central" fill="white" fontSize={isH ? 7 : 5.5} fontWeight={800} fontFamily="monospace" style={{ pointerEvents: "none", userSelect: "none" }}>{ACTION_LETTER[node.action_type] || "?"}</text>}
              </g>
            );
          })}
        </g>
      </svg>
      {hoveredData && hoveredScreenPos && <GraphHoverCard node={hoveredData} screenX={hoveredScreenPos.x} screenY={hoveredScreenPos.y} containerW={containerWidth} />}
      <div className="absolute bottom-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full text-[10px] pointer-events-none flex items-center gap-3" style={{ background: "var(--color-surface-sunken)", border: "1px solid var(--color-border)", color: "var(--color-muted-foreground)" }}>
        <span>scroll to zoom &middot; drag to pan &middot; hover for details</span>
        {criticalSet.size > 0 && (
          <>
            <span style={{ color: "var(--color-border)" }}>|</span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full" style={{ background: CRITICAL_PATH_COLOR, boxShadow: `0 0 4px ${CRITICAL_PATH_GLOW}` }} />
              <span style={{ color: CRITICAL_PATH_COLOR + "aa" }}>critical path</span>
            </span>
          </>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// TIMELINE VIEW (linear cards, straight down)
// ═══════════════════════════════════════════════════════════

function TimelineView({ dag, criticalSet }: { dag: DagData; criticalSet: Set<number> }) {
  const listRef = useRef<HTMLDivElement>(null);
  const animatedRef = useRef(false);

  useEffect(() => {
    if (animatedRef.current || !listRef.current) return;
    animatedRef.current = true;
    const cards = listRef.current.querySelectorAll("[data-tl-card]");
    gsap.set(cards, { opacity: 0, x: -16 });
    gsap.to(cards, { opacity: 1, x: 0, duration: 0.45, ease: "expo.out", stagger: { each: 0.025 } });
  }, []);

  const boundaryIndices = useMemo(() => {
    const set = new Set<number>();
    let prev: string | null = null;
    for (let i = 0; i < dag.nodes.length; i++) {
      const tid = dag.nodes[i].trace_id;
      if (tid && tid !== prev && prev !== null) set.add(i);
      if (tid) prev = tid;
    }
    return set;
  }, [dag.nodes]);

  return (
    <div
      className="relative rounded-xl overflow-hidden"
      style={{ background: "linear-gradient(180deg, var(--color-surface-sunken) 0%, var(--color-background) 100%)", border: "1px solid var(--color-border)" }}
    >
      <div ref={listRef} className="max-h-[560px] overflow-y-auto p-4 space-y-0">
        {dag.nodes.map((node, idx) => {
          const vs = getNodeVisualStatus(node);
          const s = STATUS_COLORS[vs] || STATUS_COLORS.effective;
          const accent = ACTION_COLOR[node.action_type] || "#94a3b8";
          const detail = parseDetail(node.action_detail);
          const isLast = idx === dag.nodes.length - 1;
          const isCrit = criticalSet.has(node.id);
          const showBoundary = boundaryIndices.has(idx);

          return (
            <div key={node.id}>
              {/* Trace boundary */}
              {showBoundary && (
                <div className="flex items-center gap-3 py-2.5 px-2">
                  <div className="flex-1 h-px" style={{ background: `linear-gradient(90deg, transparent, color-mix(in oklch, var(--color-info) 20%, transparent), transparent)` }} />
                  <span className="text-[9px] font-mono font-semibold uppercase tracking-widest px-2 py-0.5 rounded shrink-0" style={{ color: "var(--color-info)", opacity: 0.6, background: "color-mix(in oklch, var(--color-info) 5%, transparent)" }}>
                    trace {node.trace_id?.slice(0, 8)}
                  </span>
                  <div className="flex-1 h-px" style={{ background: `linear-gradient(90deg, transparent, color-mix(in oklch, var(--color-info) 20%, transparent), transparent)` }} />
                </div>
              )}

              <div className="flex">
                {/* Timeline spine */}
                <div className="flex flex-col items-center shrink-0" style={{ width: 28 }}>
                  {idx > 0 && !showBoundary && <div className="w-px flex-1 min-h-[6px]" style={{ background: isCrit ? CRITICAL_PATH_COLOR + "40" : "color-mix(in oklch, var(--color-border) 50%, transparent)" }} />}
                  {(idx === 0 || showBoundary) && <div className="flex-1" />}
                  <div className="relative shrink-0">
                    <div className="absolute -inset-1 rounded-full" style={{ background: isCrit ? CRITICAL_PATH_GLOW : s.glow, opacity: isCrit ? 0.25 : 0.12 }} />
                    <div className="w-3 h-3 rounded-full relative" style={{ background: s.fill, border: `1.5px solid ${isCrit ? CRITICAL_PATH_COLOR : s.stroke}`, boxShadow: `0 0 6px ${isCrit ? CRITICAL_PATH_GLOW : s.glow}` }} />
                  </div>
                  {!isLast && <div className="w-px flex-1 min-h-[6px]" style={{ background: isCrit ? CRITICAL_PATH_COLOR + "40" : "color-mix(in oklch, var(--color-border) 50%, transparent)" }} />}
                  {isLast && <div className="flex-1" />}
                </div>

                {/* Card */}
                <div data-tl-card className="flex-1 ml-2 my-[3px]">
                  <div
                    className="rounded-lg flex items-center gap-2.5 px-3 py-2"
                    style={{
                      background: node.error ? "color-mix(in oklch, var(--color-destructive) 6%, transparent)" : s.fill + "08",
                      border: `1px solid ${node.error ? "color-mix(in oklch, var(--color-destructive) 20%, transparent)" : isCrit ? CRITICAL_PATH_COLOR + "30" : s.stroke + "20"}`,
                    }}
                  >
                    {/* Action icon */}
                    <div
                      className="w-6 h-6 rounded flex items-center justify-center shrink-0 font-mono text-[9px] font-black"
                      style={{ background: node.error ? "color-mix(in oklch, var(--color-destructive) 15%, transparent)" : accent + "15", color: node.error ? "var(--color-destructive)" : accent, border: `1px solid ${node.error ? "color-mix(in oklch, var(--color-destructive) 30%, transparent)" : accent + "30"}` }}
                    >
                      {node.error ? "!" : ACTION_LETTER[node.action_type] || "?"}
                    </div>

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-[11px] font-semibold" style={{ color: node.error ? "var(--color-destructive)" : "var(--color-foreground)" }}>
                          {ACTION_WORD[node.action_type] || node.action_type}
                        </span>
                        <span className="text-[9px] font-mono text-muted-foreground opacity-60">#{node.id}</span>
                        {isCrit && (
                          <span className="text-[8px] font-bold px-1.5 py-0.5 rounded" style={{ color: CRITICAL_PATH_COLOR, background: CRITICAL_PATH_COLOR + "12", border: `1px solid ${CRITICAL_PATH_COLOR}25` }}>
                            CRIT
                          </span>
                        )}
                      </div>
                      {detail && (
                        <span className="text-[10px] font-mono block truncate text-muted-foreground opacity-70">
                          {truncate(detail, 60)}
                        </span>
                      )}
                      {node.files_touched.length > 0 && (
                        <span className="text-[9px] font-mono block truncate" style={{ color: accent + "80" }}>
                          {node.files_touched.map(f => f.split(/[/\\]/).pop()).join(", ")}
                        </span>
                      )}
                    </div>

                    {/* Right side */}
                    <div className="flex items-center gap-1.5 shrink-0">
                      {node.latency_ms > 0 && (
                        <span className="text-[9px] font-mono tabular-nums px-1.5 py-0.5 rounded text-muted-foreground" style={{ background: "color-mix(in oklch, var(--color-muted-foreground) 5%, transparent)" }}>
                          {formatLatency(node.latency_ms)}
                        </span>
                      )}
                      {node.error && (
                        <span className="text-[8px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded text-destructive"
                          style={{ background: "color-mix(in oklch, var(--color-destructive) 12%, transparent)", border: "1px solid color-mix(in oklch, var(--color-destructive) 25%, transparent)" }}>
                          FAIL
                        </span>
                      )}
                      {node.status !== "effective" && (
                        <span
                          className="text-[8px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
                          style={{ color: s.stroke, background: s.fill + "15", border: `1px solid ${s.stroke}25` }}
                        >
                          {node.status === "reverted" ? "REV" : "WST"}
                        </span>
                      )}
                      {node.reverted_by !== null && (
                        <span className="text-[8px] font-mono text-destructive opacity-60">
                          by #{node.reverted_by}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {criticalSet.size > 0 && (
        <div className="px-4 pb-3 pt-1 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ background: CRITICAL_PATH_COLOR, boxShadow: `0 0 4px ${CRITICAL_PATH_GLOW}` }} />
          <span className="text-[10px]" style={{ color: CRITICAL_PATH_COLOR + "88" }}>
            Critical path: {criticalSet.size} nodes, longest latency chain through the DAG
          </span>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// MAIN EXPORT — mode toggle between graph + timeline
// ═══════════════════════════════════════════════════════════

export function SessionDAG({ dag }: { dag: DagData }) {
  const [mode, setMode] = useState<ViewMode>("graph");

  const criticalPath = useMemo(() => dag.critical_path || [], [dag.critical_path]);
  const criticalSet = useMemo(() => new Set(criticalPath), [criticalPath]);
  const criticalEdgeSet = useMemo(() => {
    const set = new Set<string>();
    for (let i = 0; i < criticalPath.length - 1; i++) {
      set.add(`${criticalPath[i]}-${criticalPath[i + 1]}`);
    }
    return set;
  }, [criticalPath]);

  if (!dag.nodes.length) {
    return (
      <Card className="border-dashed">
        <CardContent className="py-12 text-center">
          <div className="text-sm text-muted-foreground">No DAG data available</div>
        </CardContent>
      </Card>
    );
  }

  const crossCount = dag.edges.filter(e => e.type === "cross_trace").length;
  const errorCount = dag.nodes.filter(n => n.error).length;

  return (
    <Card className="overflow-hidden border-0 shadow-none bg-transparent">
      <CardHeader className="pb-2 px-0">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold tracking-tight flex items-center gap-2">
            <span className="w-5 h-5 rounded flex items-center justify-center text-[10px] font-black"
              style={{ background: "color-mix(in oklch, var(--color-primary-accent) 10%, transparent)", color: "var(--color-primary-accent)", border: "1px solid color-mix(in oklch, var(--color-primary-accent) 20%, transparent)" }}>
              {mode === "graph" ? "G" : "T"}
            </span>
            {mode === "graph" ? "Causal DAG" : "Timeline"}
          </CardTitle>

          <div className="flex items-center gap-2.5">
            {/* Mode toggle */}
            <div
              className="flex items-center rounded-full p-0.5"
              style={{ background: "color-mix(in oklch, var(--color-muted-foreground) 8%, transparent)", border: "1px solid var(--color-border)" }}
            >
              <button
                type="button"
                onClick={() => setMode("graph")}
                className="px-2.5 py-1 rounded-full text-[10px] font-medium transition-all"
                style={{
                  background: mode === "graph" ? "color-mix(in oklch, var(--color-primary-accent) 15%, transparent)" : "transparent",
                  color: mode === "graph" ? "var(--color-primary-accent)" : "var(--color-muted-foreground)",
                  border: mode === "graph" ? "1px solid color-mix(in oklch, var(--color-primary-accent) 25%, transparent)" : "1px solid transparent",
                }}
              >
                Graph
              </button>
              <button
                type="button"
                onClick={() => setMode("timeline")}
                className="px-2.5 py-1 rounded-full text-[10px] font-medium transition-all"
                style={{
                  background: mode === "timeline" ? "color-mix(in oklch, var(--color-primary-accent) 15%, transparent)" : "transparent",
                  color: mode === "timeline" ? "var(--color-primary-accent)" : "var(--color-muted-foreground)",
                  border: mode === "timeline" ? "1px solid color-mix(in oklch, var(--color-primary-accent) 25%, transparent)" : "1px solid transparent",
                }}
              >
                Timeline
              </button>
            </div>

            <StatPills stats={dag.stats} crossCount={crossCount} errorCount={errorCount} />
          </div>
        </div>
      </CardHeader>

      <CardContent className="px-0 pt-0">
        {mode === "graph"
          ? <GraphView dag={dag} criticalSet={criticalSet} criticalEdgeSet={criticalEdgeSet} />
          : <TimelineView dag={dag} criticalSet={criticalSet} />
        }
      </CardContent>
    </Card>
  );
}
