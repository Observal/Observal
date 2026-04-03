import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageHeader, DataTable, Badge, Spinner, EmptyState } from "@/components/ui";
import { Server } from "lucide-react";

const API_KEY = localStorage.getItem("observal_api_key") || "";

async function apiFetch(path: string) {
  const r = await fetch(path, { headers: { "X-API-Key": API_KEY } });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

export function McpList() {
  const [data, setData] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => { apiFetch("/api/v1/mcps").then(setData).finally(() => setLoading(false)); }, []);

  if (loading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;
  if (!data.length) return <EmptyState icon={<Server className="h-8 w-8" />} title="No MCP servers" description="Submit one via the CLI: observal submit <git-url>" />;

  return (
    <div>
      <PageHeader title="MCP Servers" description={`${data.length} approved`} />
      <DataTable columns={[
        { key: "name", label: "Name", className: "font-medium" },
        { key: "version", label: "Version", className: "font-mono text-xs" },
        { key: "category", label: "Category", render: (r: any) => <Badge variant="outline">{r.category}</Badge> },
        { key: "owner", label: "Owner", className: "text-muted-foreground" },
        { key: "supported_ides", label: "IDEs", render: (r: any) => (r.supported_ides || []).map((ide: string) => <Badge key={ide} variant="default">{ide}</Badge>) },
      ]} data={data} onRowClick={(r) => navigate(`/mcps/${r.id}/metrics`)} />
    </div>
  );
}

export function AgentList() {
  const [data, setData] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => { apiFetch("/api/v1/agents").then(setData).finally(() => setLoading(false)); }, []);

  if (loading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;
  if (!data.length) return <EmptyState icon={<Server className="h-8 w-8" />} title="No agents" description="Create one via the CLI: observal agent create" />;

  return (
    <div>
      <PageHeader title="Agents" description={`${data.length} active`} />
      <DataTable columns={[
        { key: "name", label: "Name", className: "font-medium" },
        { key: "version", label: "Version", className: "font-mono text-xs" },
        { key: "model_name", label: "Model" },
        { key: "owner", label: "Owner", className: "text-muted-foreground" },
        { key: "supported_ides", label: "IDEs", render: (r: any) => (r.supported_ides || []).map((ide: string) => <Badge key={ide} variant="default">{ide}</Badge>) },
      ]} data={data} />
    </div>
  );
}

export function ReviewList() {
  const [data, setData] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => { apiFetch("/api/v1/review").then(setData).finally(() => setLoading(false)); }, []);

  if (loading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;
  if (!data.length) return <EmptyState title="No pending reviews" description="All submissions have been reviewed." />;

  return (
    <div>
      <PageHeader title="Pending Reviews" description={`${data.length} awaiting review`} />
      <DataTable columns={[
        { key: "name", label: "Name", className: "font-medium" },
        { key: "submitted_by", label: "Submitted By", className: "text-muted-foreground" },
        { key: "status", label: "Status", render: (r: any) => <Badge variant={r.status === "pending" ? "warning" : "outline"}>{r.status}</Badge> },
      ]} data={data} />
    </div>
  );
}

export function FeedbackPage() {
  return (
    <div>
      <PageHeader title="Feedback" description="Ratings and reviews from users" />
      <EmptyState title="Coming soon" description="View feedback for MCP servers and agents." />
    </div>
  );
}

export function EvalsPage() {
  return (
    <div>
      <PageHeader title="Evaluations" description="LLM-as-judge scorecards" />
      <EmptyState title="Coming soon" description="Run evaluations from the CLI: observal eval run <agent-id>" />
    </div>
  );
}

export function SettingsPage() {
  const [data, setData] = useState<any[]>([]);
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      apiFetch("/api/v1/admin/settings").then(setData).catch(() => {}),
      apiFetch("/api/v1/admin/users").then(setUsers).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="flex h-64 items-center justify-center"><Spinner /></div>;

  return (
    <div>
      <PageHeader title="Settings" description="Enterprise configuration and user management" />
      {data.length > 0 && (
        <div className="mb-6">
          <h3 className="mb-3 text-sm font-medium text-muted-foreground">Enterprise Settings</h3>
          <DataTable columns={[
            { key: "key", label: "Key", className: "font-mono font-medium" },
            { key: "value", label: "Value" },
          ]} data={data} />
        </div>
      )}
      {users.length > 0 && (
        <div>
          <h3 className="mb-3 text-sm font-medium text-muted-foreground">Users ({users.length})</h3>
          <DataTable columns={[
            { key: "name", label: "Name", className: "font-medium" },
            { key: "email", label: "Email" },
            { key: "role", label: "Role", render: (r: any) => <Badge variant={r.role === "admin" ? "default" : "outline"}>{r.role}</Badge> },
          ]} data={users} />
        </div>
      )}
    </div>
  );
}
