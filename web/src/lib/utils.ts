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
