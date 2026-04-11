"use client";

import { use, useState, useCallback, useMemo } from "react";
import { useOtelSession } from "@/hooks/use-api";
import type { OtelSessionData, RawOtelEvent } from "@/lib/types";
import {
  FileText,
  ChevronDown,
  ChevronRight,
  ChevronsUpDown,
  Cpu,
  Wrench,
  ShieldCheck,
  MessageSquare,
  Clock,
  Zap,
  Play,
  Square,
  Globe,
  Bot,
  Search,
  Filter,
  X,
  AlertTriangle,
  Bell,
  ListChecks,
  Minimize2,
  GitBranch,
  LogIn,
  Users,
} from "lucide-react";
import { PageHeader } from "@/components/layouts/page-header";
import { DetailSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/* ── Helpers ─────────────────────────────────────────────── */

function Badge({ children, variant = "default" }: { children: React.ReactNode; variant?: "default" | "success" | "warning" | "muted" }) {
  const cls = {
    default: "bg-primary/10 text-primary",
    success: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
    warning: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
    muted: "bg-muted text-muted-foreground",
  }[variant];
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium ${cls}`}>
      {children}
    </span>
  );
}

function Stat({ label, value, icon: Icon }: { label: string; value: string | number; icon?: React.ElementType }) {
  return (
    <div className="flex items-center gap-1.5 text-xs">
      {Icon && <Icon className="h-3 w-3 text-muted-foreground shrink-0" />}
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium font-[family-name:var(--font-mono)] tabular-nums">{value}</span>
    </div>
  );
}

function formatDuration(ms: string | number): string {
  const n = typeof ms === "string" ? parseFloat(ms) : ms;
  if (n < 1000) return `${Math.round(n)}ms`;
  return `${(n / 1000).toFixed(1)}s`;
}

function formatTokens(n: string | number): string {
  const num = typeof n === "string" ? parseInt(n, 10) : n;
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}k`;
  return `${num}`;
}

function isHookEvent(eventName: string): boolean {
  return eventName.startsWith("hook_");
}

function getEventName(evt: RawOtelEvent): string {
  return evt.attributes?.["event.name"] || evt.event_name;
}

function eventIcon(eventName: string) {
  if (eventName === "api_request") return Cpu;
  if (eventName === "tool_result") return Wrench;
  if (eventName === "tool_decision") return ShieldCheck;
  if (eventName === "user_prompt" || eventName === "hook_userpromptsubmit") return MessageSquare;
  if (eventName === "hook_posttooluse") return Wrench;
  if (eventName === "hook_pretooluse") return ShieldCheck;
  if (eventName === "hook_posttoolusefailure") return AlertTriangle;
  if (eventName === "hook_subagentstart") return Play;
  if (eventName === "hook_subagentstop") return Square;
  if (eventName === "hook_assistant_response") return Bot;
  if (eventName === "hook_stop") return Square;
  if (eventName === "hook_stopfailure") return AlertTriangle;
  if (eventName === "hook_sessionstart") return LogIn;
  if (eventName === "hook_notification") return Bell;
  if (eventName === "hook_taskcreated" || eventName === "hook_taskcompleted") return ListChecks;
  if (eventName === "hook_precompact" || eventName === "hook_postcompact") return Minimize2;
  if (eventName === "hook_worktreecreate" || eventName === "hook_worktreeremove") return GitBranch;
  if (eventName === "hook_elicitation" || eventName === "hook_elicitationresult") return Globe;
  if (isHookEvent(eventName)) return Zap;
  return FileText;
}

function eventColor(eventName: string): string {
  if (eventName === "api_request") return "text-blue-500";
  if (eventName === "tool_result") return "text-emerald-500";
  if (eventName === "tool_decision") return "text-amber-500";
  if (eventName === "user_prompt" || eventName === "hook_userpromptsubmit") return "text-purple-500";
  if (eventName === "hook_posttooluse") return "text-cyan-500";
  if (eventName === "hook_pretooluse") return "text-sky-400";
  if (eventName === "hook_posttoolusefailure" || eventName === "hook_stopfailure") return "text-red-500";
  if (eventName === "hook_subagentstart" || eventName === "hook_subagentstop") return "text-indigo-500";
  if (eventName === "hook_assistant_response") return "text-violet-500";
  if (eventName === "hook_stop") return "text-rose-500";
  if (eventName === "hook_sessionstart") return "text-green-500";
  if (eventName === "hook_notification") return "text-yellow-500";
  if (eventName === "hook_taskcreated" || eventName === "hook_taskcompleted") return "text-lime-500";
  if (eventName === "hook_precompact" || eventName === "hook_postcompact") return "text-slate-400";
  if (eventName === "hook_worktreecreate" || eventName === "hook_worktreeremove") return "text-amber-400";
  if (eventName === "hook_elicitation" || eventName === "hook_elicitationresult") return "text-teal-500";
  if (isHookEvent(eventName)) return "text-orange-500";
  return "text-muted-foreground";
}

/* ── Filter categories ───────────────────────────────────── */

type FilterCategory = {
  key: string;
  label: string;
  match: (eventName: string) => boolean;
  color: string;
};

const FILTER_CATEGORIES: FilterCategory[] = [
  { key: "prompts", label: "Prompts", match: (e) => e === "user_prompt" || e === "hook_userpromptsubmit", color: "bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/20" },
  { key: "responses", label: "Responses", match: (e) => e === "hook_assistant_response", color: "bg-violet-500/10 text-violet-600 dark:text-violet-400 border-violet-500/20" },
  { key: "tools", label: "Tools", match: (e) => ["tool_result", "tool_decision", "hook_posttooluse", "hook_pretooluse", "hook_posttoolusefailure"].includes(e), color: "bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border-cyan-500/20" },
  { key: "api", label: "API", match: (e) => e === "api_request", color: "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20" },
  { key: "agents", label: "Agents", match: (e) => e === "hook_subagentstart" || e === "hook_subagentstop", color: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border-indigo-500/20" },
  { key: "lifecycle", label: "Lifecycle", match: (e) => ["hook_sessionstart", "hook_stop", "hook_stopfailure", "hook_precompact", "hook_postcompact"].includes(e), color: "bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20" },
  { key: "tasks", label: "Tasks", match: (e) => e === "hook_taskcreated" || e === "hook_taskcompleted", color: "bg-lime-500/10 text-lime-600 dark:text-lime-400 border-lime-500/20" },
  { key: "mcp", label: "MCP", match: (e) => e === "hook_elicitation" || e === "hook_elicitationresult", color: "bg-teal-500/10 text-teal-600 dark:text-teal-400 border-teal-500/20" },
  { key: "errors", label: "Errors", match: (e) => e === "hook_posttoolusefailure" || e === "hook_stopfailure", color: "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20" },
];

/* ── Tree data structures ────────────────────────────────── */

interface AgentScope {
  agentId: string;
  agentType: string;
  startEvent?: RawOtelEvent;
  stopEvent?: RawOtelEvent;
  events: RawOtelEvent[];
}

interface Turn {
  promptEvent?: RawOtelEvent;           // The user prompt that started this turn
  responseEvent?: RawOtelEvent;         // The assistant response text
  stopEvent?: RawOtelEvent;             // The stop/end event
  topLevelEvents: RawOtelEvent[];       // Events not inside any subagent
  agents: AgentScope[];                 // Subagent scopes with their events
  allEvents: RawOtelEvent[];            // All events in this turn (for counting)
}

/* ── Dedup + Tree builder ────────────────────────────────── */

function deduplicateEvents(events: RawOtelEvent[]): RawOtelEvent[] {
  // Check if we have hook data at all
  const hasHooks = events.some((e) => isHookEvent(getEventName(e)));
  if (!hasHooks) return events;

  // Build a set of tool_use_ids covered by hooks
  const hookToolUseIds = new Set<string>();
  for (const evt of events) {
    const eName = getEventName(evt);
    const tuid = evt.attributes?.tool_use_id;
    if (tuid && isHookEvent(eName)) hookToolUseIds.add(tuid);
  }

  return events.filter((evt) => {
    const eName = getEventName(evt);

    // Remove OTEL user_prompt when we have hook_userpromptsubmit (hooks have full text)
    if (eName === "user_prompt" && hasHooks) return false;

    // Remove OTEL tool_decision/tool_result when hooks cover the same tool call
    if (eName === "tool_decision" || eName === "tool_result") {
      const tuid = evt.attributes?.tool_use_id;
      if (tuid && hookToolUseIds.has(tuid)) return false;
      // Even without matching tool_use_id, if hooks exist, they're richer
      if (hasHooks) return false;
    }

    return true;
  });
}

function buildEventTree(events: RawOtelEvent[]): { turns: Turn[]; preSessionEvents: RawOtelEvent[] } {
  const deduped = deduplicateEvents(events);
  const turns: Turn[] = [];
  const preSessionEvents: RawOtelEvent[] = [];

  let currentTurn: Turn | null = null;
  // Track open agent scopes by agent_id
  const openAgents = new Map<string, AgentScope>();

  for (const evt of deduped) {
    const eName = getEventName(evt);
    const attrs = evt.attributes ?? {};

    // Turn boundary: new prompt starts a turn
    if (eName === "hook_userpromptsubmit" || eName === "user_prompt") {
      // Close previous turn if open
      if (currentTurn) {
        turns.push(currentTurn);
        openAgents.clear();
      }
      currentTurn = {
        promptEvent: evt,
        topLevelEvents: [],
        agents: [],
        allEvents: [evt],
      };
      continue;
    }

    // If no turn started yet, these are pre-session events (session start, etc.)
    if (!currentTurn) {
      preSessionEvents.push(evt);
      continue;
    }

    currentTurn.allEvents.push(evt);

    // SubagentStart: open an agent scope
    if (eName === "hook_subagentstart") {
      const agentId = attrs.agent_id || `agent-${currentTurn.agents.length}`;
      const scope: AgentScope = {
        agentId,
        agentType: attrs.agent_type || "agent",
        startEvent: evt,
        events: [],
      };
      openAgents.set(agentId, scope);
      currentTurn.agents.push(scope);
      continue;
    }

    // SubagentStop: close the agent scope
    if (eName === "hook_subagentstop") {
      const agentId = attrs.agent_id || "";
      const scope = openAgents.get(agentId);
      if (scope) {
        scope.stopEvent = evt;
        openAgents.delete(agentId);
      } else {
        // Unmatched stop — add to top level
        currentTurn.topLevelEvents.push(evt);
      }
      continue;
    }

    // Assistant response: mark on the turn
    if (eName === "hook_assistant_response") {
      currentTurn.responseEvent = evt;
      continue;
    }

    // Stop events: mark turn end
    if (eName === "hook_stop" || eName === "hook_stopfailure") {
      currentTurn.stopEvent = evt;
      continue;
    }

    // Regular events: check if they belong to an open agent scope
    const evtAgentId = attrs.agent_id;
    if (evtAgentId && openAgents.has(evtAgentId)) {
      openAgents.get(evtAgentId)!.events.push(evt);
    } else {
      currentTurn.topLevelEvents.push(evt);
    }
  }

  // Push final turn
  if (currentTurn) turns.push(currentTurn);

  return { turns, preSessionEvents };
}

/* ── Search helper ───────────────────────────────────────── */

function eventMatchesSearch(evt: RawOtelEvent, q: string): boolean {
  const attrs = evt.attributes ?? {};
  const eName = getEventName(evt);
  return (
    eName.toLowerCase().includes(q) ||
    (evt.body || "").toLowerCase().includes(q) ||
    (attrs.tool_name || "").toLowerCase().includes(q) ||
    (attrs.tool_input || "").toLowerCase().includes(q) ||
    (attrs.tool_response || "").toLowerCase().includes(q) ||
    (attrs.agent_type || "").toLowerCase().includes(q) ||
    (attrs.agent_id || "").toLowerCase().includes(q) ||
    (attrs.error || "").toLowerCase().includes(q) ||
    (attrs.task_subject || "").toLowerCase().includes(q)
  );
}

function eventMatchesFilter(evt: RawOtelEvent, activeFilters: Set<string>): boolean {
  if (activeFilters.size === 0) return true;
  const eName = getEventName(evt);
  const activeCategories = FILTER_CATEGORIES.filter((c) => activeFilters.has(c.key));
  return activeCategories.some((cat) => cat.match(eName));
}

function turnMatchesFilters(turn: Turn, activeFilters: Set<string>, searchQuery: string): boolean {
  const q = searchQuery.toLowerCase();
  return turn.allEvents.some((evt) => {
    if (!eventMatchesFilter(evt, activeFilters)) return false;
    if (q && !eventMatchesSearch(evt, q)) return false;
    return true;
  });
}

function filterTurnEvents(events: RawOtelEvent[], activeFilters: Set<string>, searchQuery: string): RawOtelEvent[] {
  const q = searchQuery.toLowerCase();
  return events.filter((evt) => {
    if (!eventMatchesFilter(evt, activeFilters)) return false;
    if (q && !eventMatchesSearch(evt, q)) return false;
    return true;
  });
}

/* ── Event inline summary (shown without expanding) ────── */

function EventSummary({ event }: { event: RawOtelEvent }) {
  const attrs = event.attributes ?? {};
  const eName = getEventName(event);

  if (eName === "api_request") {
    return (
      <div className="flex items-center gap-3 flex-wrap">
        <Badge>{attrs.model || "?"}</Badge>
        {attrs.duration_ms && <Stat label="" value={formatDuration(attrs.duration_ms)} icon={Clock} />}
        {attrs.input_tokens && parseInt(attrs.input_tokens) > 1 && <Stat label="in" value={formatTokens(attrs.input_tokens)} />}
        {attrs.output_tokens && <Stat label="out" value={formatTokens(attrs.output_tokens)} />}
        {attrs.cache_read_tokens && parseInt(attrs.cache_read_tokens) > 0 && (
          <Stat label="cache" value={formatTokens(attrs.cache_read_tokens)} />
        )}
      </div>
    );
  }

  if (eName === "tool_result") {
    const success = attrs.success === "true";
    return (
      <div className="flex items-center gap-3 flex-wrap">
        <Badge variant={success ? "success" : "warning"}>{attrs.tool_name || "?"}</Badge>
        {attrs.duration_ms && <Stat label="" value={formatDuration(attrs.duration_ms)} icon={Clock} />}
        {!success && <Badge variant="warning">failed</Badge>}
      </div>
    );
  }

  if (eName === "tool_decision") {
    const accepted = attrs.decision === "accept";
    return (
      <div className="flex items-center gap-3 flex-wrap">
        <Badge variant={accepted ? "muted" : "warning"}>{attrs.tool_name || "?"}</Badge>
        <span className="text-xs text-muted-foreground">{accepted ? "accepted" : "rejected"}</span>
      </div>
    );
  }

  if (eName === "hook_posttooluse" || eName === "hook_pretooluse") {
    return (
      <div className="flex items-center gap-3 flex-wrap">
        <Badge variant={eName === "hook_posttooluse" ? "success" : "muted"}>{attrs.tool_name || "?"}</Badge>
      </div>
    );
  }

  if (eName === "hook_posttoolusefailure") {
    return (
      <div className="flex items-center gap-3 flex-wrap">
        <Badge variant="warning">{attrs.tool_name || "?"}</Badge>
        <span className="text-xs text-red-500">failed</span>
        {attrs.error && <span className="text-xs text-muted-foreground truncate max-w-md">{attrs.error.slice(0, 80)}</span>}
      </div>
    );
  }

  if (eName === "hook_stopfailure") {
    return (
      <div className="flex items-center gap-3 flex-wrap">
        <Badge variant="warning">API error</Badge>
        {attrs.error && <span className="text-xs text-red-500 truncate max-w-md">{attrs.error.slice(0, 80)}</span>}
      </div>
    );
  }

  if (eName === "hook_sessionstart") {
    return <Badge variant="success">{attrs.session_resumed === "True" ? "resumed" : "new session"}</Badge>;
  }

  if (eName === "hook_notification") {
    return (
      <div className="flex items-center gap-3 flex-wrap">
        {attrs.notification_title && <Badge>{attrs.notification_title}</Badge>}
        {attrs.tool_response && <span className="text-xs text-muted-foreground truncate max-w-md">{attrs.tool_response.slice(0, 80)}</span>}
      </div>
    );
  }

  if (eName === "hook_taskcreated" || eName === "hook_taskcompleted") {
    return (
      <div className="flex items-center gap-3 flex-wrap">
        <Badge variant={eName === "hook_taskcompleted" ? "success" : "default"}>
          {attrs.task_subject || attrs.task_id || "task"}
        </Badge>
      </div>
    );
  }

  if (eName === "hook_precompact" || eName === "hook_postcompact") {
    return <Badge variant="muted">{eName === "hook_precompact" ? "compacting" : "compacted"}</Badge>;
  }

  if (eName === "hook_worktreecreate" || eName === "hook_worktreeremove") {
    return (
      <div className="flex items-center gap-3 flex-wrap">
        <Badge>{attrs.branch || "worktree"}</Badge>
        <span className="text-xs text-muted-foreground">{eName === "hook_worktreecreate" ? "created" : "removed"}</span>
      </div>
    );
  }

  if (eName === "hook_elicitation" || eName === "hook_elicitationresult") {
    return (
      <div className="flex items-center gap-3 flex-wrap">
        <Badge>{attrs.mcp_server_name || "MCP"}</Badge>
        <span className="text-xs text-muted-foreground">{eName === "hook_elicitation" ? "ask" : "reply"}</span>
      </div>
    );
  }

  if (isHookEvent(eName)) {
    return (
      <div className="flex items-center gap-3 flex-wrap">
        <Badge>{attrs.tool_name || attrs.agent_type || eName.replace("hook_", "")}</Badge>
      </div>
    );
  }

  return null;
}

/* ── Pretty JSON / content block ──────────────────────── */

function ContentBlock({ label, content }: { label: string; content: string }) {
  let display = content;
  let isJson = false;
  try {
    const parsed = JSON.parse(content);
    display = JSON.stringify(parsed, null, 2);
    isJson = true;
  } catch { /* not JSON */ }

  const lines = display.split("\n").length;
  const isLong = lines > 20;
  const [showFull, setShowFull] = useState(false);
  const shown = isLong && !showFull ? display.split("\n").slice(0, 20).join("\n") + "\n..." : display;

  return (
    <div className="space-y-1">
      <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">{label}</span>
      <pre className={`text-xs font-[family-name:var(--font-mono)] whitespace-pre-wrap break-all bg-background/50 border border-border rounded-md p-2.5 max-h-[400px] overflow-auto ${isJson ? "text-foreground" : "text-foreground/80"}`}>
        {shown}
      </pre>
      {isLong && (
        <button type="button" onClick={() => setShowFull(!showFull)} className="text-[11px] text-primary-accent hover:underline">
          {showFull ? "Show less" : `Show all ${lines} lines`}
        </button>
      )}
    </div>
  );
}

/* ── Event detail (shown when expanded) ────────────────── */

function EventDetail({ event }: { event: RawOtelEvent }) {
  const attrs = event.attributes ?? {};
  const eName = getEventName(event);

  if (isHookEvent(eName) && (attrs.tool_input || attrs.tool_response)) {
    return (
      <div className="ml-6 mr-3 mb-2 mt-1 space-y-3">
        {attrs.tool_input && <ContentBlock label="Input" content={attrs.tool_input} />}
        {attrs.tool_response && <ContentBlock label="Response" content={attrs.tool_response} />}
        <HookMetaGrid attrs={attrs} />
      </div>
    );
  }

  const skip = new Set(["event.name", "event.sequence", "event.timestamp", "session.id", "user.id", "terminal.type", "prompt.id"]);
  const entries = Object.entries(attrs).filter(([k]) => !skip.has(k)).sort(([a], [b]) => a.localeCompare(b));
  if (entries.length === 0) return null;

  return (
    <div className="ml-6 mr-3 mb-2 mt-1">
      <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-xs font-[family-name:var(--font-mono)] bg-surface-sunken rounded-md p-3">
        {entries.map(([key, value]) => (
          <div key={key} className="contents">
            <span className="text-muted-foreground">{key}</span>
            <span className="text-foreground truncate">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function HookMetaGrid({ attrs }: { attrs: Record<string, string> }) {
  const skip = new Set(["event.name", "session.id", "tool_input", "tool_response", "hook_event", "tool_name"]);
  const entries = Object.entries(attrs).filter(([k]) => !skip.has(k)).sort(([a], [b]) => a.localeCompare(b));
  if (entries.length === 0) return null;
  return (
    <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-xs font-[family-name:var(--font-mono)] bg-surface-sunken rounded-md p-2">
      {entries.map(([key, value]) => (
        <div key={key} className="contents">
          <span className="text-muted-foreground">{key}</span>
          <span className="text-foreground truncate">{value}</span>
        </div>
      ))}
    </div>
  );
}

/* ── Friendly event label ────────────────────────────────── */

function eventLabel(evt: RawOtelEvent): string {
  const eName = getEventName(evt);
  const attrs = evt.attributes ?? {};
  if (eName === "hook_posttooluse" || eName === "hook_pretooluse") return attrs.tool_name || "tool";
  if (eName === "hook_posttoolusefailure") return attrs.tool_name || "tool fail";
  if (eName === "hook_taskcreated") return "task new";
  if (eName === "hook_taskcompleted") return "task done";
  if (eName === "hook_precompact") return "compact";
  if (eName === "hook_postcompact") return "compacted";
  if (eName === "hook_worktreecreate") return "worktree+";
  if (eName === "hook_worktreeremove") return "worktree-";
  if (eName === "hook_elicitation") return "MCP ask";
  if (eName === "hook_elicitationresult") return "MCP reply";
  if (eName === "hook_notification") return "notify";
  if (eName === "hook_sessionstart") return "session";
  if (isHookEvent(eName)) return attrs.tool_name || eName.replace("hook_", "");
  return eName;
}

/* ── Leaf event row (used inside tree) ───────────────────── */

function LeafEvent({ event, isExpanded, onToggle, depth = 0 }: {
  event: RawOtelEvent;
  isExpanded: boolean;
  onToggle: () => void;
  depth?: number;
}) {
  const eName = getEventName(event);
  const attrs = event.attributes ?? {};
  const Icon = eventIcon(eName);
  const color = eventColor(eName);

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center gap-2 w-full text-left py-1.5 px-3 rounded-md hover:bg-muted/50 transition-colors"
        style={{ paddingLeft: `${12 + depth * 20}px` }}
      >
        {isExpanded
          ? <ChevronDown className="h-3 w-3 text-muted-foreground shrink-0" />
          : <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" />}
        <Icon className={`h-3.5 w-3.5 shrink-0 ${color}`} />
        <span className="text-xs font-medium w-24 shrink-0 truncate">{eventLabel(event)}</span>
        {attrs.agent_id && (
          <span className="text-[10px] px-1 py-0.5 rounded bg-indigo-500/10 text-indigo-500 font-medium shrink-0">
            {attrs.agent_type || "agent"}
          </span>
        )}
        <div className="flex-1 min-w-0">
          <EventSummary event={event} />
        </div>
        {event.timestamp && (
          <span className="ml-auto text-[10px] text-muted-foreground tabular-nums shrink-0 pl-2">
            {new Date(event.timestamp).toLocaleTimeString()}
          </span>
        )}
      </button>
      {isExpanded && <div style={{ paddingLeft: `${depth * 20}px` }}><EventDetail event={event} /></div>}
    </div>
  );
}

/* ── Agent scope node (collapsible sub-tree) ─────────────── */

function AgentNode({ agent, expandedSet, onToggleEvent, activeFilters, searchQuery, depth = 1 }: {
  agent: AgentScope;
  expandedSet: Set<string>;
  onToggleEvent: (key: string) => void;
  activeFilters: Set<string>;
  searchQuery: string;
  depth?: number;
}) {
  const nodeKey = `agent-${agent.agentId}`;
  const isOpen = expandedSet.has(nodeKey);
  const filtered = filterTurnEvents(agent.events, activeFilters, searchQuery);
  const totalInAgent = agent.events.length;

  if (filtered.length === 0 && activeFilters.size > 0) return null;

  return (
    <div>
      <button
        type="button"
        onClick={() => onToggleEvent(nodeKey)}
        className="flex items-center gap-2 w-full text-left py-1.5 px-3 rounded-md hover:bg-indigo-500/5 transition-colors"
        style={{ paddingLeft: `${12 + depth * 20}px` }}
      >
        {isOpen
          ? <ChevronDown className="h-3.5 w-3.5 text-indigo-500 shrink-0" />
          : <ChevronRight className="h-3.5 w-3.5 text-indigo-500 shrink-0" />}
        <Users className="h-3.5 w-3.5 text-indigo-500 shrink-0" />
        <span className="text-xs font-semibold text-indigo-600 dark:text-indigo-400">{agent.agentType}</span>
        <Badge variant="muted">{filtered.length} event{filtered.length !== 1 ? "s" : ""}</Badge>
        {agent.startEvent?.timestamp && (
          <span className="ml-auto text-[10px] text-muted-foreground tabular-nums shrink-0">
            {new Date(agent.startEvent.timestamp).toLocaleTimeString()}
            {agent.stopEvent?.timestamp && (
              <> — {new Date(agent.stopEvent.timestamp).toLocaleTimeString()}</>
            )}
          </span>
        )}
      </button>
      {isOpen && (
        <div className="border-l-2 border-indigo-500/20" style={{ marginLeft: `${22 + depth * 20}px` }}>
          {filtered.length === 0 ? (
            <p className="text-xs text-muted-foreground py-2 pl-4">No matching events in this agent.</p>
          ) : (
            filtered.map((evt, i) => {
              const key = `agent-${agent.agentId}-evt-${i}`;
              return (
                <LeafEvent
                  key={key}
                  event={evt}
                  isExpanded={expandedSet.has(key)}
                  onToggle={() => onToggleEvent(key)}
                  depth={depth + 1}
                />
              );
            })
          )}
          {totalInAgent > filtered.length && activeFilters.size > 0 && (
            <p className="text-[10px] text-muted-foreground pl-4 py-1">
              {totalInAgent - filtered.length} event{totalInAgent - filtered.length !== 1 ? "s" : ""} hidden by filters
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Turn node (collapsible root) ────────────────────────── */

function TurnNode({ turn, index, expandedSet, onToggleEvent, activeFilters, searchQuery }: {
  turn: Turn;
  index: number;
  expandedSet: Set<string>;
  onToggleEvent: (key: string) => void;
  activeFilters: Set<string>;
  searchQuery: string;
}) {
  const nodeKey = `turn-${index}`;
  const isOpen = expandedSet.has(nodeKey);
  const attrs = turn.promptEvent?.attributes ?? {};
  const promptPreview = (attrs.tool_input || attrs.prompt_text || "").slice(0, 120);

  const filteredTop = filterTurnEvents(turn.topLevelEvents, activeFilters, searchQuery);
  const hasMatchingAgents = turn.agents.some((a) => {
    const agentFiltered = filterTurnEvents(a.events, activeFilters, searchQuery);
    return agentFiltered.length > 0 || activeFilters.size === 0;
  });

  // Count totals for the turn
  const toolCount = turn.allEvents.filter((e) => {
    const en = getEventName(e);
    return en === "hook_posttooluse" || en === "hook_pretooluse" || en === "tool_result";
  }).length;
  const apiCount = turn.allEvents.filter((e) => getEventName(e) === "api_request").length;
  const agentCount = turn.agents.length;

  // Timestamps
  const startTime = turn.promptEvent?.timestamp;
  const endTime = turn.stopEvent?.timestamp || turn.responseEvent?.timestamp;
  const duration = startTime && endTime
    ? new Date(endTime).getTime() - new Date(startTime).getTime()
    : null;

  return (
    <div className="rounded-lg border border-border overflow-hidden">
      {/* Turn header */}
      <button
        type="button"
        onClick={() => onToggleEvent(nodeKey)}
        className="flex items-start gap-2 w-full text-left py-2.5 px-3 hover:bg-purple-500/5 transition-colors"
      >
        {isOpen
          ? <ChevronDown className="h-4 w-4 text-purple-500 mt-0.5 shrink-0" />
          : <ChevronRight className="h-4 w-4 text-purple-500 mt-0.5 shrink-0" />}
        <MessageSquare className="h-4 w-4 text-purple-500 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold">Turn {index + 1}</span>
            <div className="flex items-center gap-1.5">
              {toolCount > 0 && <Badge variant="muted"><Wrench className="h-2.5 w-2.5 mr-0.5 inline" />{toolCount}</Badge>}
              {apiCount > 0 && <Badge variant="muted"><Cpu className="h-2.5 w-2.5 mr-0.5 inline" />{apiCount}</Badge>}
              {agentCount > 0 && <Badge variant="default"><Users className="h-2.5 w-2.5 mr-0.5 inline" />{agentCount}</Badge>}
              {duration !== null && <Stat label="" value={formatDuration(duration)} icon={Clock} />}
            </div>
          </div>
          {promptPreview && (
            <p className="text-xs text-muted-foreground mt-1 truncate max-w-2xl">
              {promptPreview}{(attrs.tool_input?.length ?? 0) > 120 ? "..." : ""}
            </p>
          )}
        </div>
        {startTime && (
          <span className="text-[10px] text-muted-foreground tabular-nums shrink-0 mt-1">
            {new Date(startTime).toLocaleTimeString()}
          </span>
        )}
      </button>

      {/* Turn children */}
      {isOpen && (
        <div className="border-t border-border">
          {/* Top-level events (not inside any agent) */}
          {filteredTop.map((evt, i) => {
            const key = `turn-${index}-evt-${i}`;
            return (
              <LeafEvent
                key={key}
                event={evt}
                isExpanded={expandedSet.has(key)}
                onToggle={() => onToggleEvent(key)}
                depth={1}
              />
            );
          })}

          {/* Agent sub-trees */}
          {turn.agents.map((agent, ai) => (
            <AgentNode
              key={`turn-${index}-agent-${ai}`}
              agent={agent}
              expandedSet={expandedSet}
              onToggleEvent={onToggleEvent}
              activeFilters={activeFilters}
              searchQuery={searchQuery}
              depth={1}
            />
          ))}

          {/* Response at the bottom of the turn */}
          {turn.responseEvent && (() => {
            const key = `turn-${index}-response`;
            const respAttrs = turn.responseEvent.attributes ?? {};
            const preview = (respAttrs.tool_response || "").slice(0, 200);
            return (
              <div>
                <button
                  type="button"
                  onClick={() => onToggleEvent(key)}
                  className="flex items-center gap-2 w-full text-left py-1.5 px-3 hover:bg-violet-500/5 transition-colors"
                  style={{ paddingLeft: "32px" }}
                >
                  {expandedSet.has(key)
                    ? <ChevronDown className="h-3 w-3 text-violet-500 shrink-0" />
                    : <ChevronRight className="h-3 w-3 text-violet-500 shrink-0" />}
                  <Bot className="h-3.5 w-3.5 text-violet-500 shrink-0" />
                  <span className="text-xs font-medium text-violet-600 dark:text-violet-400 w-20 shrink-0">response</span>
                  <span className="text-xs text-muted-foreground truncate flex-1">{preview}{preview.length >= 200 ? "..." : ""}</span>
                </button>
                {expandedSet.has(key) && turn.responseEvent && (
                  <div style={{ paddingLeft: "20px" }}>
                    <EventDetail event={turn.responseEvent} />
                  </div>
                )}
              </div>
            );
          })()}

          {/* Turn end marker */}
          {turn.stopEvent && (
            <div className="flex items-center gap-2 py-1 px-3 text-[10px] text-muted-foreground" style={{ paddingLeft: "32px" }}>
              <Square className="h-2.5 w-2.5 text-rose-400" />
              <span>{turn.stopEvent.attributes?.stop_reason || "end_turn"}</span>
              {turn.stopEvent.timestamp && (
                <span className="ml-auto tabular-nums">{new Date(turn.stopEvent.timestamp).toLocaleTimeString()}</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Session summary stats ─────────────────────────────── */

function SessionStats({ events }: { events: RawOtelEvent[] }) {
  const stats = useMemo(() => {
    let totalInputTokens = 0;
    let totalOutputTokens = 0;
    let totalCacheRead = 0;
    let apiCalls = 0;
    let toolCalls = 0;
    let hookEvents = 0;
    const models = new Set<string>();
    const tools: Record<string, number> = {};

    for (const evt of events) {
      const attrs = evt.attributes ?? {};
      const eName = getEventName(evt);

      if (eName === "api_request") {
        apiCalls++;
        if (attrs.input_tokens) totalInputTokens += parseInt(attrs.input_tokens, 10);
        if (attrs.output_tokens) totalOutputTokens += parseInt(attrs.output_tokens, 10);
        if (attrs.cache_read_tokens) totalCacheRead += parseInt(attrs.cache_read_tokens, 10);
        if (attrs.model) models.add(attrs.model);
      }

      if (eName === "tool_result") {
        toolCalls++;
        const tn = attrs.tool_name || "unknown";
        tools[tn] = (tools[tn] || 0) + 1;
      }

      if (isHookEvent(eName)) {
        hookEvents++;
        if (attrs.tool_name && attrs.tool_name !== "user_prompt" && attrs.tool_name !== "assistant_response") {
          const tn = attrs.tool_name;
          tools[tn] = (tools[tn] || 0) + 1;
        }
      }
    }

    return { totalInputTokens, totalOutputTokens, totalCacheRead, apiCalls, toolCalls, hookEvents, models, tools };
  }, [events]);

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
      <div className="space-y-1">
        <p className="text-[11px] text-muted-foreground uppercase tracking-wide">Input Tokens</p>
        <p className="text-lg font-semibold tabular-nums">{formatTokens(stats.totalInputTokens)}</p>
      </div>
      <div className="space-y-1">
        <p className="text-[11px] text-muted-foreground uppercase tracking-wide">Output Tokens</p>
        <p className="text-lg font-semibold tabular-nums">{formatTokens(stats.totalOutputTokens)}</p>
      </div>
      <div className="space-y-1">
        <p className="text-[11px] text-muted-foreground uppercase tracking-wide">Cache Read</p>
        <p className="text-lg font-semibold tabular-nums">{formatTokens(stats.totalCacheRead)}</p>
      </div>
      <div className="space-y-1">
        <p className="text-[11px] text-muted-foreground uppercase tracking-wide">API Calls</p>
        <p className="text-lg font-semibold tabular-nums">{stats.apiCalls}</p>
      </div>
      <div className="space-y-1">
        <p className="text-[11px] text-muted-foreground uppercase tracking-wide">Tool Calls</p>
        <p className="text-lg font-semibold tabular-nums">{stats.toolCalls}</p>
      </div>
      {stats.hookEvents > 0 && (
        <div className="space-y-1">
          <p className="text-[11px] text-muted-foreground uppercase tracking-wide">Hook Captures</p>
          <p className="text-lg font-semibold tabular-nums text-orange-500">{stats.hookEvents}</p>
        </div>
      )}
      <div className="space-y-1">
        <p className="text-[11px] text-muted-foreground uppercase tracking-wide">Models</p>
        <div className="flex flex-wrap gap-1">
          {[...stats.models].map((m) => <Badge key={m}>{m.replace("claude-", "")}</Badge>)}
        </div>
      </div>
      {Object.keys(stats.tools).length > 0 && (
        <div className="col-span-full space-y-1">
          <p className="text-[11px] text-muted-foreground uppercase tracking-wide">Tools Used</p>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(stats.tools).sort(([, a], [, b]) => b - a).map(([tool, count]) => (
              <Badge key={tool} variant="muted">{tool} ({count})</Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Page ───────────────────────────────────────────────── */

export default function TraceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, isLoading, isError, error, refetch } = useOtelSession(id);

  const session = data as OtelSessionData;
  const events: RawOtelEvent[] = useMemo(() => session?.events ?? [], [session]);

  const [expandedSet, setExpandedSet] = useState<Set<string>>(new Set());
  const [activeFilters, setActiveFilters] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");

  const toggleFilter = useCallback((key: string) => {
    setActiveFilters((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const clearFilters = useCallback(() => {
    setActiveFilters(new Set());
    setSearchQuery("");
  }, []);

  // Build the tree
  const tree = useMemo(() => buildEventTree(events), [events]);

  // Filter counts (on deduplicated events)
  const allDeduped = useMemo(() => deduplicateEvents(events), [events]);
  const filterCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const cat of FILTER_CATEGORIES) {
      counts[cat.key] = allDeduped.filter((evt) => cat.match(getEventName(evt))).length;
    }
    return counts;
  }, [allDeduped]);

  // Visible turns after filtering
  const visibleTurns = useMemo(() => {
    if (activeFilters.size === 0 && !searchQuery.trim()) return tree.turns;
    return tree.turns.filter((t) => turnMatchesFilters(t, activeFilters, searchQuery));
  }, [tree.turns, activeFilters, searchQuery]);

  const onToggleEvent = useCallback((key: string) => {
    setExpandedSet((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const expandAllTurns = useCallback(() => {
    setExpandedSet((prev) => {
      const allTurnKeys = visibleTurns.map((_, i) => `turn-${tree.turns.indexOf(visibleTurns[i])}`);
      const allOpen = allTurnKeys.every((k) => prev.has(k));
      if (allOpen) return new Set(); // collapse all
      const next = new Set(prev);
      for (const k of allTurnKeys) next.add(k);
      return next;
    });
  }, [visibleTurns, tree.turns]);

  return (
    <>
      <PageHeader
        title={isLoading ? "Session" : id.slice(0, 16) + "..."}
        breadcrumbs={[
          { label: "Dashboard", href: "/dashboard" },
          { label: "Traces", href: "/traces" },
          { label: id.slice(0, 12) + "..." },
        ]}
      />
      <div className="p-6 max-w-6xl mx-auto space-y-6">
        {isLoading ? (
          <DetailSkeleton />
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : !data ? (
          <ErrorState message="Session not found" />
        ) : (
          <>
            {/* Header info */}
            <div className="animate-in flex flex-wrap items-center gap-x-6 gap-y-2">
              <div>
                <span className="text-xs text-muted-foreground block mb-0.5">Session ID</span>
                <span className="text-sm font-[family-name:var(--font-mono)]">{id}</span>
              </div>
              {session.service_name && (
                <div>
                  <span className="text-xs text-muted-foreground block mb-0.5">Service</span>
                  <span className="text-sm">{session.service_name}</span>
                </div>
              )}
              {events.length > 0 && events[0]?.timestamp && (
                <div>
                  <span className="text-xs text-muted-foreground block mb-0.5">First Event</span>
                  <span className="text-sm tabular-nums">{new Date(events[0].timestamp).toLocaleString()}</span>
                </div>
              )}
              {events.length > 0 && (
                <div>
                  <span className="text-xs text-muted-foreground block mb-0.5">Duration</span>
                  <span className="text-sm tabular-nums">
                    {events.length > 1 && events[events.length - 1]?.timestamp && events[0]?.timestamp
                      ? formatDuration(new Date(events[events.length - 1].timestamp).getTime() - new Date(events[0].timestamp).getTime())
                      : "-"}
                  </span>
                </div>
              )}
              <div>
                <span className="text-xs text-muted-foreground block mb-0.5">Turns</span>
                <span className="text-sm font-semibold tabular-nums">{tree.turns.length}</span>
              </div>
            </div>

            <Separator />
            <SessionStats events={events} />
            <Separator />

            {/* Events tree */}
            {events.length === 0 ? (
              <EmptyState icon={FileText} title="No events in this session" description="Events will appear here once telemetry data is recorded." />
            ) : (
              <div className="animate-in stagger-1 space-y-2">
                {/* Search + Filter bar */}
                <div className="space-y-2 mb-3">
                  <div className="flex items-center gap-2">
                    <div className="relative flex-1 max-w-sm">
                      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                      <Input
                        placeholder="Search events, tools, content..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="pl-8 h-8 text-sm"
                      />
                      {searchQuery && (
                        <button type="button" onClick={() => setSearchQuery("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                          <X className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                    <Button variant="ghost" size="sm" onClick={expandAllTurns} className="h-8 text-xs gap-1">
                      <ChevronsUpDown className="h-3 w-3" />
                      Toggle turns
                    </Button>
                  </div>
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <Filter className="h-3 w-3 text-muted-foreground shrink-0" />
                    {FILTER_CATEGORIES.filter((cat) => filterCounts[cat.key] > 0).map((cat) => (
                      <button
                        type="button"
                        key={cat.key}
                        onClick={() => toggleFilter(cat.key)}
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border transition-all ${
                          activeFilters.has(cat.key) ? cat.color + " border-current" : "bg-muted/50 text-muted-foreground border-transparent hover:bg-muted"
                        }`}
                      >
                        {cat.label}
                        <span className="opacity-60">{filterCounts[cat.key]}</span>
                      </button>
                    ))}
                    {(activeFilters.size > 0 || searchQuery) && (
                      <button type="button" onClick={clearFilters} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[11px] text-muted-foreground hover:text-foreground">
                        <X className="h-3 w-3" /> Clear
                      </button>
                    )}
                  </div>
                </div>

                {/* Turn count */}
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">
                    {visibleTurns.length === tree.turns.length
                      ? `${tree.turns.length} turn${tree.turns.length !== 1 ? "s" : ""}`
                      : `${visibleTurns.length} of ${tree.turns.length} turns`}
                    {" · "}{allDeduped.length} events (deduped from {events.length})
                  </span>
                </div>

                {/* Pre-session events */}
                {tree.preSessionEvents.length > 0 && (
                  <div className="rounded-lg border border-border/50 p-2 space-y-0.5">
                    <span className="text-[10px] text-muted-foreground uppercase tracking-wide px-2">Pre-session</span>
                    {tree.preSessionEvents.map((evt, i) => {
                      const key = `pre-${i}`;
                      return (
                        <LeafEvent key={key} event={evt} isExpanded={expandedSet.has(key)} onToggle={() => onToggleEvent(key)} depth={0} />
                      );
                    })}
                  </div>
                )}

                {/* Turn nodes */}
                {visibleTurns.length === 0 ? (
                  <div className="text-center py-8 text-sm text-muted-foreground">No turns match your filters.</div>
                ) : (
                  <div className="space-y-2">
                    {visibleTurns.map((turn) => {
                      const originalIndex = tree.turns.indexOf(turn);
                      return (
                        <TurnNode
                          key={`turn-${originalIndex}`}
                          turn={turn}
                          index={originalIndex}
                          expandedSet={expandedSet}
                          onToggleEvent={onToggleEvent}
                          activeFilters={activeFilters}
                          searchQuery={searchQuery}
                        />
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
