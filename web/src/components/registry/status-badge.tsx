import { cn } from "@/lib/utils";

const statusConfig: Record<string, { bg: string; text: string; dot?: string; ping?: boolean }> = {
  pending:   { bg: "bg-light-yellow", text: "text-dark-yellow", dot: "bg-dark-yellow", ping: true },
  approved:  { bg: "bg-light-green",  text: "text-dark-green",  dot: "bg-dark-green",  ping: true },
  active:    { bg: "bg-light-green",  text: "text-dark-green",  dot: "bg-dark-green",  ping: true },
  rejected:  { bg: "bg-light-red",    text: "text-dark-red" },
  inactive:  { bg: "bg-light-red",    text: "text-dark-red" },
  failed:    { bg: "bg-light-red",    text: "text-dark-red" },
  error:     { bg: "bg-light-red",    text: "text-dark-red" },
  running:   { bg: "bg-light-blue",   text: "text-dark-blue",   dot: "bg-dark-blue",   ping: true },
  completed: { bg: "bg-light-green",  text: "text-dark-green" },
  success:   { bg: "bg-light-green",  text: "text-dark-green" },
};

const fallback = { bg: "bg-muted", text: "text-muted-foreground" };

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const s = statusConfig[status.toLowerCase()] ?? fallback;

  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium", s.bg, s.text, className)}>
      {s.dot && (
        <span className="relative inline-flex h-1.5 w-1.5">
          {s.ping && (
            <span className={cn("absolute inline-flex h-full w-full animate-ping rounded-full opacity-75", s.dot)} />
          )}
          <span className={cn("relative inline-flex h-1.5 w-1.5 rounded-full", s.dot)} />
        </span>
      )}
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}
