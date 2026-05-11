// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const formatter = Intl.NumberFormat("en", { notation: "compact" });

export function compactNumber(n: number): string {
  return formatter.format(n);
}

export function formatNumber(n: number, decimals = 0): string {
  return n.toLocaleString("en-US", { maximumFractionDigits: decimals });
}

/**
 * Copy text to the clipboard.
 *
 * Uses the modern Clipboard API when available (secure contexts — HTTPS or
 * localhost). Falls back to a hidden textarea + execCommand("copy") so that
 * copy works on plain HTTP self-hosted deployments too.
 */
export async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Clipboard API can throw even when present (e.g. permissions denied
      // in non-secure contexts). Fall through to legacy path.
    }
  }

  // Legacy fallback for non-secure contexts (plain HTTP)
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}
