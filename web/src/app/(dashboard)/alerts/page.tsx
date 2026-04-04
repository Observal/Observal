"use client";

import { useState, useEffect, useCallback } from "react";
import { Bell, Plus, Trash2 } from "lucide-react";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { NoData } from "@/components/dashboard/no-data";
import { StatusBadge } from "@/components/registry/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { format } from "date-fns";

interface AlertRule {
  id: string;
  name: string;
  metric: "error_rate" | "latency_p99" | "token_usage";
  threshold: number;
  condition: "above" | "below";
  targetType: "mcp" | "agent" | "all";
  targetId: string;
  webhookUrl: string;
  status: "active" | "paused";
  lastTriggered: string | null;
}

const STORAGE_KEY = "observal_alert_rules";

function loadAlerts(): AlertRule[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveAlerts(alerts: AlertRule[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(alerts));
}

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<AlertRule[]>([]);
  const [open, setOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);

  // Form state
  const [name, setName] = useState("");
  const [metric, setMetric] = useState<AlertRule["metric"]>("error_rate");
  const [threshold, setThreshold] = useState("");
  const [condition, setCondition] = useState<AlertRule["condition"]>("above");
  const [targetType, setTargetType] = useState<AlertRule["targetType"]>("all");
  const [targetId, setTargetId] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");

  useEffect(() => { setAlerts(loadAlerts()); }, []);

  const persist = useCallback((next: AlertRule[]) => {
    setAlerts(next);
    saveAlerts(next);
  }, []);

  const handleCreate = () => {
    const rule: AlertRule = {
      id: crypto.randomUUID(),
      name,
      metric,
      threshold: Number(threshold),
      condition,
      targetType,
      targetId: targetType === "all" ? "" : targetId,
      webhookUrl,
      status: "active",
      lastTriggered: null,
    };
    persist([...alerts, rule]);
    setOpen(false);
    setName(""); setThreshold(""); setTargetId(""); setWebhookUrl("");
  };

  const toggleStatus = (id: string) => {
    persist(alerts.map((a) => a.id === id ? { ...a, status: a.status === "active" ? "paused" as const : "active" as const } : a));
  };

  const confirmDelete = () => {
    if (deleteId) persist(alerts.filter((a) => a.id !== deleteId));
    setDeleteId(null);
  };

  return (
    <DashboardShell>
      <PageHeader
        title="Alerts"
        actionButtonsRight={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button size="sm"><Plus className="h-3.5 w-3.5" /> Create Alert</Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Create Alert Rule</DialogTitle>
                <DialogDescription>Get notified when a metric crosses a threshold.</DialogDescription>
              </DialogHeader>
              <div className="grid gap-3 py-2">
                <div className="grid gap-1.5">
                  <Label>Name</Label>
                  <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="High error rate" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="grid gap-1.5">
                    <Label>Metric</Label>
                    <Select value={metric} onValueChange={(v) => setMetric(v as AlertRule["metric"])}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="error_rate">Error Rate</SelectItem>
                        <SelectItem value="latency_p99">Latency P99</SelectItem>
                        <SelectItem value="token_usage">Token Usage</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="grid gap-1.5">
                    <Label>Condition</Label>
                    <Select value={condition} onValueChange={(v) => setCondition(v as AlertRule["condition"])}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="above">Above</SelectItem>
                        <SelectItem value="below">Below</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="grid gap-1.5">
                  <Label>Threshold</Label>
                  <Input type="number" value={threshold} onChange={(e) => setThreshold(e.target.value)} placeholder="0.05" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="grid gap-1.5">
                    <Label>Target Type</Label>
                    <Select value={targetType} onValueChange={(v) => setTargetType(v as AlertRule["targetType"])}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All</SelectItem>
                        <SelectItem value="mcp">MCP Server</SelectItem>
                        <SelectItem value="agent">Agent</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  {targetType !== "all" && (
                    <div className="grid gap-1.5">
                      <Label>Target ID</Label>
                      <Input value={targetId} onChange={(e) => setTargetId(e.target.value)} placeholder="UUID" />
                    </div>
                  )}
                </div>
                <div className="grid gap-1.5">
                  <Label>Webhook URL</Label>
                  <Input value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)} placeholder="https://hooks.example.com/alert" />
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
                <Button onClick={handleCreate} disabled={!name || !threshold}>Create</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        }
      />
      <DashboardContent>
        {alerts.length === 0 ? (
          <NoData
            noDataText="No alert rules configured."
            description="Create one to get notified when metrics exceed thresholds."
          >
            <Bell className="mx-auto mt-2 h-8 w-8 text-muted-foreground/40" />
          </NoData>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Metric</TableHead>
                <TableHead>Condition</TableHead>
                <TableHead>Threshold</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Last Triggered</TableHead>
                <TableHead className="w-20" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {alerts.map((a) => (
                <TableRow key={a.id}>
                  <TableCell className="font-medium">{a.name}</TableCell>
                  <TableCell className="text-xs">{a.metric.replace("_", " ")}</TableCell>
                  <TableCell className="text-xs">{a.condition}</TableCell>
                  <TableCell>{a.threshold}</TableCell>
                  <TableCell className="text-xs">{a.targetType === "all" ? "All" : `${a.targetType}: ${a.targetId.slice(0, 8)}…`}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <Switch checked={a.status === "active"} onCheckedChange={() => toggleStatus(a.id)} />
                      <StatusBadge status={a.status} />
                    </div>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {a.lastTriggered ? format(new Date(a.lastTriggered), "MMM d, HH:mm") : "Never"}
                  </TableCell>
                  <TableCell>
                    <Button variant="ghost" size="icon" onClick={() => setDeleteId(a.id)}>
                      <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}

        {/* Delete confirmation */}
        <Dialog open={!!deleteId} onOpenChange={() => setDeleteId(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete Alert Rule</DialogTitle>
              <DialogDescription>This action cannot be undone.</DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleteId(null)}>Cancel</Button>
              <Button variant="destructive" onClick={confirmDelete}>Delete</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </DashboardContent>
    </DashboardShell>
  );
}
