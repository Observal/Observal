"use client";

import { useState, useRef, useCallback } from "react";
import { Search, TrendingUp, Clock, Check, Copy, Terminal } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { AgentCard } from "@/components/registry/agent-card";
import { useRegistryList, useTopAgents } from "@/hooks/use-api";
import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/layouts/page-header";
import { CardSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";

export default function RegistryHome() {
  const [search, setSearch] = useState("");
  const [heroCopied, setHeroCopied] = useState(false);
  const router = useRouter();
  const {
    data: agents,
    isLoading: agentsLoading,
    isError: agentsError,
    error: agentsErr,
    refetch: refetchAgents,
  } = useRegistryList("agents");
  const { data: topAgents, isLoading: topLoading } = useTopAgents();

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (search.trim()) {
      router.push(`/agents?search=${encodeURIComponent(search.trim())}`);
    }
  }

  const handleHeroCopy = useCallback(() => {
    navigator.clipboard.writeText("observal pull my-agent --ide cursor");
    setHeroCopied(true);
    toast.success("Copied to clipboard");
    setTimeout(() => setHeroCopied(false), 2000);
  }, []);

  const trending = topAgents?.slice(0, 6) ?? [];
  const recentlyAdded = (agents ?? [])
    .filter((a: any) => a.status === "approved")
    .sort((a: any, b: any) => {
      const da = a.created_at ? new Date(a.created_at).getTime() : 0;
      const db = b.created_at ? new Date(b.created_at).getTime() : 0;
      return db - da;
    })
    .slice(0, 6);

  return (
    <>
      <PageHeader
        title="Agent Registry"
        breadcrumbs={[{ label: "Registry" }]}
      />

      <div className="p-6 lg:p-8 max-w-[1200px] space-y-12">
        {/* Hero section */}
        <section className="animate-in space-y-6 pt-2">
          <div className="space-y-3 max-w-2xl">
            <h1 className="text-2xl sm:text-3xl font-display font-bold tracking-tight text-foreground">
              Observal
            </h1>
            <p className="text-base text-muted-foreground leading-relaxed max-w-lg">
              The open registry for AI agents. Browse, install, and evaluate
              agents across your team.
            </p>
          </div>

          {/* Search bar */}
          <form onSubmit={handleSearch} className="relative max-w-lg">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search agents by name, owner, or description..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 h-10"
            />
          </form>

          {/* Terminal snippet */}
          <div className="max-w-lg">
            <div className="flex items-center gap-2 rounded-md border border-border bg-surface-sunken px-3 py-2.5">
              <Terminal className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              <code className="flex-1 text-sm font-mono text-foreground select-all">
                <span className="text-muted-foreground">$</span>{" "}
                observal pull my-agent --ide cursor
              </code>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                onClick={handleHeroCopy}
                aria-label="Copy command"
              >
                {heroCopied ? (
                  <Check className="h-3.5 w-3.5 text-success" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
              </Button>
            </div>
          </div>
        </section>

        {/* Trending Agents */}
        <section className="animate-in stagger-1 space-y-4">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold font-display uppercase tracking-wider text-muted-foreground">
              Trending
            </h2>
          </div>
          {topLoading ? (
            <CardSkeleton count={3} columns={3} />
          ) : trending.length === 0 ? (
            <EmptyState
              icon={TrendingUp}
              title="No trending agents"
              description="Agents with the most downloads will appear here."
            />
          ) : (
            <div
              className="grid gap-4"
              style={{
                gridTemplateColumns:
                  "repeat(auto-fill, minmax(min(320px, 100%), 1fr))",
              }}
            >
              {trending.map((item: any, i: number) => (
                <AgentCard
                  key={item.id}
                  id={item.id}
                  name={item.name}
                  downloads={item.value}
                  description={item.description}
                  owner={item.owner}
                  version={item.version}
                  className={`animate-in stagger-${Math.min(i + 1, 5)}`}
                />
              ))}
            </div>
          )}
        </section>

        {/* Recently Added */}
        <section className="animate-in stagger-2 space-y-4">
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-sm font-semibold font-display uppercase tracking-wider text-muted-foreground">
              Recently Added
            </h2>
          </div>
          {agentsLoading ? (
            <CardSkeleton count={3} columns={3} />
          ) : agentsError ? (
            <ErrorState
              message={agentsErr?.message}
              onRetry={() => refetchAgents()}
            />
          ) : recentlyAdded.length === 0 ? (
            <EmptyState
              icon={Clock}
              title="No agents yet"
              description="Approved agents will appear here. Submit your first agent to get started."
              actionLabel="Browse Agents"
              actionHref="/agents"
            />
          ) : (
            <div
              className="grid gap-4"
              style={{
                gridTemplateColumns:
                  "repeat(auto-fill, minmax(min(320px, 100%), 1fr))",
              }}
            >
              {recentlyAdded.map((agent: any, i: number) => (
                <AgentCard
                  key={agent.id}
                  id={agent.id}
                  name={agent.name}
                  description={agent.description}
                  owner={agent.owner}
                  version={agent.version}
                  score={agent.score}
                  component_count={
                    agent.component_links?.length ??
                    agent.mcp_links?.length
                  }
                  className={`animate-in stagger-${Math.min(i + 1, 5)}`}
                />
              ))}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
