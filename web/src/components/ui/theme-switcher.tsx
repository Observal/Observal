"use client";

import { useTheme } from "next-themes";
import { Check, Palette } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SidebarMenuButton } from "@/components/ui/sidebar";

const themes = [
  { value: "light", label: "Light", color: "bg-white border border-gray-300" },
  { value: "dark", label: "Dark", color: "bg-zinc-800" },
  { value: "midnight", label: "Midnight", color: "bg-[hsl(230,35%,7%)]" },
  { value: "forest", label: "Forest", color: "bg-[hsl(150,20%,7%)]" },
  { value: "sunset", label: "Sunset", color: "bg-[hsl(25,30%,8%)]" },
] as const;

export function ThemeSwitcher() {
  const { theme, setTheme } = useTheme();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <SidebarMenuButton tooltip="Theme">
          <Palette />
          <span>Theme</span>
        </SidebarMenuButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" className="w-40">
        {themes.map((t) => (
          <DropdownMenuItem key={t.value} onClick={() => setTheme(t.value)}>
            <span className={`size-3 shrink-0 rounded-full ${t.color}`} />
            <span>{t.label}</span>
            {theme === t.value && <Check className="ml-auto size-3.5" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
