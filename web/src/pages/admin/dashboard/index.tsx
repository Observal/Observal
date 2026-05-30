// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { Suspense } from "react";
import { useLocation, useSearch } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { PageHeader } from "@/components/layouts/page-header";
import { AdoptionTab } from "./components/adoption-tab";
import { CostTab } from "./components/cost-tab";
import { InvestmentsTab } from "./components/investments-tab";
import { InsightsTab } from "./components/insights-tab";
import { DepartmentsTab } from "./components/departments-tab";
import { VelocityTab } from "./components/velocity-tab";
import { useExecAdoption, useExecAgentCounts, useExecConfig } from "@/hooks/use-api";
import { RefreshCw, Calendar, Rocket, Download } from "lucide-react";
import { useState, useCallback } from "react";
import { DashboardRangeContext } from "./context";

const TABS = ["adoption", "cost", "investments", "insights", "departments", "velocity"] as const;
type TabId = typeof TABS[number];

const RANGES = [
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "90d", label: "90 days" },
] as const;

function OnboardingWizard({ onDismiss }: { onDismiss: () => void }) {
  return (
    <div className="rounded-lg border border-dashed border-primary/30 bg-primary/5 p-6">
      <div className="flex items-start gap-4">
        <div className="rounded-full bg-primary/10 p-2.5 mt-0.5">
          <Rocket className="h-5 w-5 text-primary" />
        </div>
        <div className="flex-1">
          <h3 className="text-base font-semibold mb-1">Welcome to the Executive Dashboard</h3>
          <p className="text-sm text-muted-foreground mb-4">
            Set up these three things to unlock the full dashboard experience:
          </p>
          <ol className="space-y-3">
            <li className="flex items-start gap-3">
              <span className="flex-shrink-0 flex items-center justify-center w-6 h-6 rounded-full bg-primary text-primary-foreground text-xs font-bold">1</span>
              <div>
                <p className="text-sm font-medium">Assign departments to users</p>
                <p className="text-xs text-muted-foreground">
                  Go to Users &rarr; click a user &rarr; set their department. Or configure SSO groups for automatic mapping.
                </p>
              </div>
            </li>
            <li className="flex items-start gap-3">
              <span className="flex-shrink-0 flex items-center justify-center w-6 h-6 rounded-full bg-primary text-primary-foreground text-xs font-bold">2</span>
              <div>
                <p className="text-sm font-medium">Set cost baselines</p>
                <p className="text-xs text-muted-foreground">
                  Open the Cost Intelligence tab and enter what tasks cost before AI. This enables savings calculations and ROI projections.
                </p>
              </div>
            </li>
            <li className="flex items-start gap-3">
              <span className="flex-shrink-0 flex items-center justify-center w-6 h-6 rounded-full bg-primary text-primary-foreground text-xs font-bold">3</span>
              <div>
                <p className="text-sm font-medium">Categorize your agents</p>
                <p className="text-xs text-muted-foreground">
                  In the Agent Builder, assign categories (Code Review, Testing, etc.) so the dashboard can group usage and costs.
                </p>
              </div>
            </li>
          </ol>
          <button
            onClick={onDismiss}
            className="mt-4 text-xs text-muted-foreground hover:text-foreground transition-colors underline underline-offset-2"
          >
            Dismiss — I&apos;ll set this up later
          </button>
        </div>
      </div>
    </div>
  );
}

function ExportDropdown({ activeTab }: { activeTab: string }) {
  const [open, setOpen] = useState(false);

  const handleCSV = useCallback(() => {
    setOpen(false);
    // Collect visible table data from the DOM
    const tables = document.querySelectorAll("table");
    if (tables.length === 0) {
      alert("No table data on this tab. Switch to Departments, Velocity, or Investments for exportable data.");
      return;
    }
    const rows: string[] = [];
    tables.forEach((table) => {
      const headers = Array.from(table.querySelectorAll("thead th")).map((th) => th.textContent?.trim() ?? "");
      if (headers.length > 0) rows.push(headers.join(","));
      table.querySelectorAll("tbody tr").forEach((tr) => {
        const cells = Array.from(tr.querySelectorAll("td")).map((td) => {
          const text = td.textContent?.trim()?.replace(/,/g, " ") ?? "";
          return text;
        });
        if (cells.length > 0) rows.push(cells.join(","));
      });
      rows.push("");
    });
    const blob = new Blob([rows.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `observal-dashboard-${activeTab}-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [activeTab]);

  const handlePrint = useCallback(() => {
    setOpen(false);
    window.print();
  }, []);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-border hover:bg-muted/50 transition-colors"
      >
        <Download className="h-3 w-3" />
        Export
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-50 rounded-md border border-border bg-background shadow-md py-1 min-w-[120px]">
            <button
              onClick={handleCSV}
              className="w-full text-left px-3 py-1.5 text-xs hover:bg-muted/50 transition-colors"
            >
              Export as CSV
            </button>
            <button
              onClick={handlePrint}
              className="w-full text-left px-3 py-1.5 text-xs hover:bg-muted/50 transition-colors"
            >
              Print / PDF
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function DashboardContent() {
  const { tab: tabParam, range: rangeParam } = useSearch({ from: "/_authed/_admin/dashboard" });
  const { pathname } = useLocation();
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState<TabId>(() =>
    tabParam && TABS.includes(tabParam as TabId) ? (tabParam as TabId) : "adoption"
  );

  const [activeRange, setActiveRange] = useState(() =>
    rangeParam && ["7d", "30d", "90d"].includes(rangeParam) ? rangeParam : "30d"
  );

  const [refreshing, setRefreshing] = useState(false);
  const [wizardDismissed, setWizardDismissed] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("observal_dash_onboarding_dismissed") === "1";
    }
    return false;
  });

  const { data: adoption } = useExecAdoption();
  const { data: agents } = useExecAgentCounts();
  const { data: config } = useExecConfig();

  const showOnboarding = !wizardDismissed && (
    (adoption?.departments_covered ?? 0) === 0 &&
    !config &&
    (agents?.total ?? 0) === 0
  );

  const handleTabChange = useCallback((value: string) => {
    setActiveTab(value as TabId);
    const params = new URLSearchParams(window.location.search);
    params.set("tab", value);
    window.history.replaceState(null, "", `${pathname}?${params.toString()}`);
  }, [pathname]);

  const handleRangeChange = useCallback((value: string) => {
    setActiveRange(value);
    const params = new URLSearchParams(window.location.search);
    params.set("range", value);
    window.history.replaceState(null, "", `${pathname}?${params.toString()}`);
  }, [pathname]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    await queryClient.invalidateQueries({
      queryKey: ["exec"],
      predicate: (query) => query.queryKey[1] !== "ai-insights",
    });
    setTimeout(() => setRefreshing(false), 600);
  }, [queryClient]);

  const handleDismissWizard = useCallback(() => {
    setWizardDismissed(true);
    localStorage.setItem("observal_dash_onboarding_dismissed", "1");
  }, []);

  return (
    <DashboardRangeContext.Provider value={activeRange}>
      <PageHeader
        title="Executive Dashboard"
        breadcrumbs={[{ label: "Dashboard" }]}
      />
      <div className="p-6 w-full mx-auto space-y-6">
        {showOnboarding && <OnboardingWizard onDismiss={handleDismissWizard} />}

        {/* Controls row */}
        <div className="flex items-center justify-between">
          {/* Range picker */}
          <div className="flex items-center gap-2">
            <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
            <div className="flex items-center gap-0.5 p-0.5 rounded-md bg-muted/40 border border-border">
              {RANGES.map((r) => (
                <button
                  key={r.value}
                  onClick={() => handleRangeChange(r.value)}
                  className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                    activeRange === r.value
                      ? "bg-background shadow-sm text-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Export */}
            <ExportDropdown activeTab={activeTab} />

            {/* Refresh button */}
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-border hover:bg-muted/50 transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`h-3 w-3 ${refreshing ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>

        <Tabs value={activeTab} onValueChange={handleTabChange} className="w-full">
          <TabsList className="grid w-full grid-cols-6">
            <TabsTrigger value="adoption">AI Adoption</TabsTrigger>
            <TabsTrigger value="cost">Cost Intelligence</TabsTrigger>
            <TabsTrigger value="investments">Investments</TabsTrigger>
            <TabsTrigger value="insights">AI Insights</TabsTrigger>
            <TabsTrigger value="departments">Departments</TabsTrigger>
            <TabsTrigger value="velocity">Velocity</TabsTrigger>
          </TabsList>

          <TabsContent value="adoption">
            <AdoptionTab />
          </TabsContent>

          <TabsContent value="cost">
            <CostTab />
          </TabsContent>

          <TabsContent value="investments">
            <InvestmentsTab />
          </TabsContent>

          <TabsContent value="insights">
            <InsightsTab />
          </TabsContent>

          <TabsContent value="departments">
            <DepartmentsTab />
          </TabsContent>

          <TabsContent value="velocity">
            <VelocityTab />
          </TabsContent>
        </Tabs>
      </div>
    </DashboardRangeContext.Provider>
  );
}

export default function DashboardPage() {
  return (
    <Suspense fallback={<div className="p-6 animate-pulse" />}>
      <DashboardContent />
    </Suspense>
  );
}
