function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function exportToCsv(data: Record<string, unknown>[], filename: string) {
  if (!data.length) return;
  const keys = Object.keys(data[0]);
  const rows = [
    keys.join(","),
    ...data.map((row) =>
      keys.map((k) => {
        const v = String(row[k] ?? "");
        return v.includes(",") || v.includes('"') ? `"${v.replace(/"/g, '""')}"` : v;
      }).join(",")
    ),
  ];
  downloadBlob(new Blob([rows.join("\n")], { type: "text/csv" }), filename);
}

export function exportToJson(data: Record<string, unknown>[], filename: string) {
  downloadBlob(
    new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
    filename
  );
}
