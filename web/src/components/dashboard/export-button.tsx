"use client";

import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { exportToCsv, exportToJson } from "@/lib/export";

interface ExportButtonProps {
  data: Record<string, unknown>[];
  filename: string;
  label?: string;
}

export function ExportButton({ data, filename, label = "Export" }: ExportButtonProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm">
          <Download className="mr-1.5 size-3.5" />
          {label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => exportToCsv(data, `${filename}.csv`)}>
          Export CSV
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => exportToJson(data, `${filename}.json`)}>
          Export JSON
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
