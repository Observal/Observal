"use client";

import { useState } from "react";
import Link from "next/link";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { useRegistryList } from "@/hooks/use-api";
import type { RegistryType } from "@/lib/api";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

const TYPES: { value: RegistryType; label: string }[] = [
  { value: "mcps", label: "MCPs" },
  { value: "skills", label: "Skills" },
  { value: "hooks", label: "Hooks" },
  { value: "prompts", label: "Prompts" },
  { value: "sandboxes", label: "Sandboxes" },
];

function ComponentTable({ type, search }: { type: RegistryType; search: string }) {
  const { data, isLoading } = useRegistryList(type, search ? { search } : undefined);
  const items = data ?? [];

  if (isLoading) return <p className="text-sm text-muted-foreground py-4">Loading...</p>;
  if (items.length === 0) return <p className="text-sm text-muted-foreground py-4">No {type} found</p>;

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Description</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item: any) => (
          <TableRow key={item.id}>
            <TableCell>
              <Link href={`/components/${item.id}?type=${type}`} className="font-medium hover:underline">
                {item.name}
              </Link>
            </TableCell>
            <TableCell className="text-muted-foreground text-xs max-w-xs truncate">
              {item.description ?? "-"}
            </TableCell>
            <TableCell>
              <Badge variant={item.status === "approved" ? "default" : "secondary"}>
                {item.status}
              </Badge>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export default function ComponentsPage() {
  const [search, setSearch] = useState("");

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      <h1 className="text-xl font-semibold">Components</h1>

      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search components..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      <Tabs defaultValue="mcps">
        <TabsList>
          {TYPES.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>{t.label}</TabsTrigger>
          ))}
        </TabsList>
        {TYPES.map((t) => (
          <TabsContent key={t.value} value={t.value} className="mt-4">
            <ComponentTable type={t.value} search={search} />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
