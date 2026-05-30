// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useTheme } from "@/lib/theme";
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
  { value: "solarized-light", label: "Solarized Light", color: "bg-[#fdf6e3] border border-gray-300" },
  { value: "dark", label: "Dark", color: "bg-zinc-800" },
  { value: "midnight", label: "Midnight", color: "bg-[hsl(230,35%,7%)]" },
  { value: "forest", label: "Forest", color: "bg-[hsl(150,20%,7%)]" },
  { value: "sunset", label: "Sunset", color: "bg-[hsl(25,30%,8%)]" },
  { value: "solarized-dark", label: "Solarized Dark", color: "bg-[#002b36]" },
  { value: "dracula", label: "Dracula", color: "bg-[#282a36]" },
  { value: "nord", label: "Nord", color: "bg-[#2e3440]" },
  { value: "monokai", label: "Monokai", color: "bg-[#272822]" },
  { value: "gruvbox", label: "Gruvbox", color: "bg-[#282828]" },
  { value: "catppuccin", label: "Catppuccin", color: "bg-[#1e1e2e]" },
  { value: "tokyo-night", label: "Tokyo Night", color: "bg-[#1a1b26]" },
  { value: "one-dark", label: "One Dark", color: "bg-[#282c34]" },
  { value: "rose-pine", label: "Rosé Pine", color: "bg-[#191724]" },
];

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
