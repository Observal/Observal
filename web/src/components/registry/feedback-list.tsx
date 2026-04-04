"use client";

export function FeedbackList({ data, isLoading }: { data: Record<string, unknown>[] | undefined; isLoading: boolean }) {
  if (isLoading) return <p className="text-sm text-muted-foreground">Loading feedback…</p>;
  if (!data?.length) return <p className="text-sm text-muted-foreground">No feedback yet.</p>;
  return (
    <div className="space-y-3">
      {data.map((fb, i) => (
        <div key={i} className="rounded-md border p-3">
          <div className="flex items-center gap-2 text-sm">
            <span className="font-medium">{"★".repeat(Number(fb.stars ?? 0))}</span>
            <span className="text-muted-foreground">{String(fb.username ?? "Anonymous")}</span>
          </div>
          {fb.comment ? <p className="mt-1 text-sm">{String(fb.comment)}</p> : null}
        </div>
      ))}
    </div>
  );
}
