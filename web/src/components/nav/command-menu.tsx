"use client";

import { useEffect, useState } from "react";
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
import { allNavItems } from "./registry-sidebar";

export function CommandMenu() {
  const [open, setOpen] = useState(false);
  const router = useRouter();

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
