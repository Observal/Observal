import { NavLink, Outlet } from "react-router-dom";
import { cn } from "@/lib/utils";
import {
  LayoutDashboard, Activity, Server, Bot, ShieldCheck,
  MessageSquare, FlaskConical, Settings, ChevronLeft, ChevronRight,
} from "lucide-react";
import { useState } from "react";

const NAV = [
  { to: "/", icon: LayoutDashboard, label: "Overview" },
  { to: "/traces", icon: Activity, label: "Traces" },
  { to: "/mcps", icon: Server, label: "MCP Servers" },
  { to: "/agents", icon: Bot, label: "Agents" },
  { to: "/reviews", icon: ShieldCheck, label: "Reviews" },
  { to: "/feedback", icon: MessageSquare, label: "Feedback" },
  { to: "/evals", icon: FlaskConical, label: "Evaluations" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className={cn(
        "flex flex-col border-r border-border bg-card transition-all duration-200",
        collapsed ? "w-16" : "w-56"
      )}>
        <div className="flex h-14 items-center gap-2 border-b border-border px-4">
          {!collapsed && <span className="text-lg font-bold">Observal</span>}
          <button onClick={() => setCollapsed(!collapsed)}
            className="ml-auto rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </button>
        </div>
        <nav className="flex-1 space-y-1 p-2">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink key={to} to={to} end={to === "/"}
              className={({ isActive }) => cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                collapsed && "justify-center px-2"
              )}>
              <Icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span>{label}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-border p-3">
          {!collapsed && <p className="text-xs text-muted-foreground">v0.1.0</p>}
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto p-6">
        <Outlet />
      </main>
    </div>
  );
}
