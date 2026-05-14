// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { useEffect, useState } from "react";
import { Activity, Bot, LayoutDashboard, Settings } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { useTraces } from "@/hooks/use-api";
import { allNavItems } from "./registry-sidebar";

export function CommandMenu() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const { data: recentTraces = [] } = useTraces();

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);

  const onSelect = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Search agents, components, traces..." />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>
        <CommandGroup heading="Top pages">
          <CommandItem onSelect={() => onSelect("/traces")}>
            <Activity className="mr-2 h-4 w-4" />
            Traces
          </CommandItem>
          <CommandItem onSelect={() => onSelect("/dashboard")}>
            <LayoutDashboard className="mr-2 h-4 w-4" />
            Dashboard
          </CommandItem>
          <CommandItem onSelect={() => onSelect("/settings")}>
            <Settings className="mr-2 h-4 w-4" />
            Settings
          </CommandItem>
          <CommandItem onSelect={() => onSelect("/agents")}>
            <Bot className="mr-2 h-4 w-4" />
            Agents
          </CommandItem>
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Navigate">
          {allNavItems.map((group) =>
            group.items.map((item) => (
              <CommandItem
                key={item.href}
                onSelect={() => onSelect(item.href)}
              >
                <item.icon className="mr-2 h-4 w-4" />
                {item.title}
              </CommandItem>
            )),
          )}
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Recent traces">
          {recentTraces.slice(0, 5).map((trace) => {
            const traceId = String(trace.traceId ?? "");
            const name = String(trace.name ?? trace.traceType ?? traceId);
            return (
              <CommandItem
                key={traceId}
                onSelect={() => onSelect(`/traces/${traceId}`)}
              >
                <Activity className="mr-2 h-4 w-4" />
                {name}
              </CommandItem>
            );
          })}
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading="Quick Actions">
          <CommandItem onSelect={() => onSelect("/agents/builder")}>
            <span className="mr-2 text-sm">+</span>
            New Agent
          </CommandItem>
          <CommandItem onSelect={() => onSelect("/agents?search=")}>
            <span className="mr-2 text-sm">?</span>
            Search Agents
          </CommandItem>
          <CommandItem onSelect={() => onSelect("/components?search=")}>
            <span className="mr-2 text-sm">?</span>
            Search Components
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
