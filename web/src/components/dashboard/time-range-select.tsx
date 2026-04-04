"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const options = [
  { value: "24h", label: "Last 24 hours" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
];

interface TimeRangeSelectProps {
  value: string;
  onChange: (v: string) => void;
}

export function TimeRangeSelect({ value, onChange }: TimeRangeSelectProps) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-7 w-auto gap-1 border-none bg-transparent px-2 text-xs font-medium shadow-none">
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="start">
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value} className="text-xs">
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
