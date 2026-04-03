import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("rounded-lg border border-border bg-card p-6", className)}>{children}</div>;
}

export function StatCard({ title, value, subtitle, trend, icon }: {
  title: string; value: string | number; subtitle?: string; trend?: "up" | "down" | "neutral";
  icon?: ReactNode;
}) {
  return (
    <Card>
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{title}</p>
        {icon && <span className="text-muted-foreground">{icon}</span>}
      </div>
      <p className="mt-2 text-3xl font-bold">{value}</p>
      {subtitle && (
        <p className={cn("mt-1 text-sm", trend === "up" ? "text-success" : trend === "down" ? "text-destructive" : "text-muted-foreground")}>
          {subtitle}
        </p>
      )}
    </Card>
  );
}

export function Badge({ children, variant = "default" }: { children: ReactNode; variant?: "default" | "success" | "warning" | "destructive" | "outline" }) {
  const styles = {
    default: "bg-primary/10 text-primary",
    success: "bg-success/10 text-success",
    warning: "bg-warning/10 text-warning",
    destructive: "bg-destructive/10 text-destructive",
    outline: "border border-border text-muted-foreground",
  };
  return <span className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium", styles[variant])}>{children}</span>;
}

export function Spinner() {
  return <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />;
}

export function EmptyState({ icon, title, description }: { icon?: ReactNode; title: string; description?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      {icon && <div className="mb-4 text-muted-foreground">{icon}</div>}
      <h3 className="text-lg font-medium">{title}</h3>
      {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
    </div>
  );
}

export function PageHeader({ title, description, children }: { title: string; description?: string; children?: ReactNode }) {
  return (
    <div className="mb-6 flex items-center justify-between">
      <div>
        <h1 className="text-2xl font-bold">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {children}
    </div>
  );
}

export function DataTable({ columns, data, onRowClick }: {
  columns: { key: string; label: string; className?: string; render?: (row: any) => ReactNode }[];
  data: any[]; onRowClick?: (row: any) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/50">
            {columns.map(col => (
              <th key={col.key} className={cn("px-4 py-3 text-left font-medium text-muted-foreground", col.className)}>{col.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, i) => (
            <tr key={i} onClick={() => onRowClick?.(row)}
              className={cn("border-b border-border transition-colors", onRowClick && "cursor-pointer hover:bg-muted/30")}>
              {columns.map(col => (
                <td key={col.key} className={cn("px-4 py-3", col.className)}>
                  {col.render ? col.render(row) : row[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Tabs({ tabs, active, onChange }: { tabs: { key: string; label: string; count?: number }[]; active: string; onChange: (key: string) => void }) {
  return (
    <div className="flex gap-1 border-b border-border">
      {tabs.map(tab => (
        <button key={tab.key} onClick={() => onChange(tab.key)}
          className={cn("px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px",
            active === tab.key ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
          {tab.label}{tab.count !== undefined && <span className="ml-1.5 text-xs text-muted-foreground">({tab.count})</span>}
        </button>
      ))}
    </div>
  );
}
