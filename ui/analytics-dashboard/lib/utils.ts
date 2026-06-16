import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(v: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v);
}

export function formatPct(v: number, decimals = 1): string {
  return `${v.toFixed(decimals)}%`;
}

export function formatNumber(v: number): string {
  return new Intl.NumberFormat("en-US").format(v);
}
