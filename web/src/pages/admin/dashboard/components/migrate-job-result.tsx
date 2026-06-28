// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useMigrationDownloadToken } from "@/hooks/use-admin-api";
import type {
	MigrationJob,
	MigrationExportResult,
	MigrationImportResult,
	MigrationValidateResult,
} from "@/lib/types/admin";

interface MigrateJobResultProps {
	job: MigrationJob;
	onReset: () => void;
}

export function MigrateJobResult({ job, onReset }: MigrateJobResultProps) {
	const downloadTokenMutation = useMigrationDownloadToken();

	const handleDownload = async (name: string) => {
		downloadTokenMutation.mutate(
			{ jobId: job.id, name },
			{
				onSuccess: (data) => {
					// Open download URL in new tab
					const url = `/api/v1/admin/migrate/download?token=${encodeURIComponent(data.token)}`;
					window.open(url, "_blank");
				},
			},
		);
	};

	if (job.status === "failed") {
		return (
			<div className="space-y-4 py-4">
				<div className="rounded-md border border-red-500/30 bg-red-500/5 p-3">
					<p className="text-sm font-medium text-red-700 dark:text-red-400">
						Job Failed
					</p>
					<p className="mt-1 text-xs text-red-600 dark:text-red-300">
						{job.error_message || "An unknown error occurred"}
					</p>
				</div>
				<button
					onClick={onReset}
					className="w-full px-4 py-2 text-sm font-medium rounded-md border border-border hover:bg-muted/50 transition-colors"
				>
					Try Again
				</button>
			</div>
		);
	}

	const result = job.result;

	return (
		<div className="space-y-4 py-4">
			<div className="rounded-md border border-green-500/30 bg-green-500/5 p-3">
				<p className="text-sm font-medium text-green-700 dark:text-green-400">
					Completed Successfully
				</p>
			</div>

			{/* Export result */}
			{job.operation_type === "export" && result && (
				<ExportResultView result={result as MigrationExportResult} />
			)}

			{/* Import result */}
			{job.operation_type === "import" && result && (
				<ImportResultView result={result as MigrationImportResult} />
			)}

			{/* Validate result */}
			{job.operation_type === "validate" && result && (
				<ValidateResultView result={result as MigrationValidateResult} />
			)}

			{/* Download buttons for artifacts */}
			{job.artifacts && job.artifacts.length > 0 && (
				<div className="space-y-2">
					<p className="text-xs font-medium">Download Artifacts</p>
					<div className="space-y-1">
						{job.artifacts.map((a) => (
							<button
								key={a.name}
								onClick={() => handleDownload(a.name)}
								disabled={downloadTokenMutation.isPending}
								className="flex items-center justify-between w-full px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted/50 transition-colors"
							>
								<span className="truncate">{a.name}</span>
								<span className="text-muted-foreground ml-2">
									{formatBytes(a.size_bytes)}
								</span>
							</button>
						))}
					</div>
				</div>
			)}

			{/* Schema version diff */}
			{result &&
				"schema_version_diff" in result &&
				result.schema_version_diff && (
					<p className="text-xs text-yellow-600 dark:text-yellow-400">
						Schema version difference: {result.schema_version_diff}
					</p>
				)}

			<button
				onClick={onReset}
				className="w-full px-4 py-2 text-sm font-medium rounded-md border border-border hover:bg-muted/50 transition-colors"
			>
				Start New Operation
			</button>
		</div>
	);
}

function ExportResultView({ result }: { result: MigrationExportResult }) {
	return (
		<div className="space-y-2">
			<p className="text-xs font-medium">Export Summary</p>
			<div className="grid grid-cols-2 gap-2 text-xs">
				<div>
					<span className="text-muted-foreground">Total rows:</span>{" "}
					{result.total_rows.toLocaleString()}
				</div>
				{result.archive_size_bytes != null && (
					<div>
						<span className="text-muted-foreground">Archive:</span>{" "}
						{formatBytes(result.archive_size_bytes)}
					</div>
				)}
				{result.telemetry_size_bytes != null && (
					<div>
						<span className="text-muted-foreground">Telemetry:</span>{" "}
						{formatBytes(result.telemetry_size_bytes)}
					</div>
				)}
			</div>
			{Object.keys(result.table_counts).length > 0 && (
				<details className="text-xs">
					<summary className="cursor-pointer text-muted-foreground hover:text-foreground">
						Table breakdown ({Object.keys(result.table_counts).length} tables)
					</summary>
					<div className="mt-1 max-h-32 overflow-y-auto space-y-0.5 pl-2">
						{Object.entries(result.table_counts).map(([t, c]) => (
							<div key={t} className="flex justify-between">
								<span className="truncate">{t}</span>
								<span className="text-muted-foreground">{c}</span>
							</div>
						))}
					</div>
				</details>
			)}
		</div>
	);
}

function ImportResultView({ result }: { result: MigrationImportResult }) {
	const totalInserted = Object.values(result.rows_inserted).reduce(
		(a, b) => a + b,
		0,
	);
	const totalSkipped = Object.values(result.rows_skipped).reduce(
		(a, b) => a + b,
		0,
	);

	return (
		<div className="space-y-2">
			<p className="text-xs font-medium">Import Summary</p>
			<div className="grid grid-cols-2 gap-2 text-xs">
				<div>
					<span className="text-muted-foreground">Inserted:</span>{" "}
					{totalInserted.toLocaleString()}
				</div>
				<div>
					<span className="text-muted-foreground">Skipped:</span>{" "}
					{totalSkipped.toLocaleString()}
				</div>
			</div>
			{result.tables_skipped.length > 0 && (
				<p className="text-xs text-yellow-600 dark:text-yellow-400">
					Tables skipped (not on instance):{" "}
					{result.tables_skipped.join(", ")}
				</p>
			)}
		</div>
	);
}

function ValidateResultView({ result }: { result: MigrationValidateResult }) {
	return (
		<div className="space-y-2">
			<p className="text-xs font-medium">Validation Summary</p>
			<div className="text-xs">
				<span className="text-muted-foreground">Checksums:</span>{" "}
				<span
					className={
						result.checksums_valid
							? "text-green-600 dark:text-green-400"
							: "text-red-600 dark:text-red-400"
					}
				>
					{result.checksums_valid ? "All valid" : "Some invalid"}
				</span>
			</div>
			{result.orphaned_fk_refs &&
				Object.keys(result.orphaned_fk_refs).length > 0 && (
					<p className="text-xs text-yellow-600 dark:text-yellow-400">
						Orphaned FK references found in{" "}
						{Object.keys(result.orphaned_fk_refs).length} column(s)
					</p>
				)}
		</div>
	);
}

function formatBytes(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	if (bytes < 1024 * 1024 * 1024)
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}
