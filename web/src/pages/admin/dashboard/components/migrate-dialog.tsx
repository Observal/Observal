// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { useHelp } from "@/components/wiki/help-context";
import { HelpCircle, Loader2 } from "lucide-react";
import { MigrateExportForm } from "./migrate-export-form";
import { MigrateImportForm } from "./migrate-import-form";
import { MigrateValidateForm } from "./migrate-validate-form";
import { MigrateJobResult } from "./migrate-job-result";
import { useMigrationJob } from "@/hooks/use-admin-api";
import type { MigrationJob } from "@/lib/types/admin";

interface MigrateDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
}

type TabId = "export" | "import" | "validate";

function JobProgress({ job }: { job: MigrationJob | undefined }) {
	const phase = job?.progress_phase || job?.status || "queued";
	const message = job?.progress_message || "Starting job...";
	const pct = Math.max(0, Math.min(100, job?.progress_pct ?? 0));

	return (
		<div className="space-y-4 rounded-md border border-border bg-muted/20 p-4">
			<div className="flex items-start justify-between gap-3">
				<div>
					<p className="text-sm font-medium capitalize">{phase}</p>
					<p className="mt-1 text-xs leading-5 text-muted-foreground">{message}</p>
				</div>
				<Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-muted-foreground" />
			</div>
			<div className="space-y-1.5">
				<div className="h-2 overflow-hidden rounded-full bg-muted">
					<div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
				</div>
				<div className="flex justify-between text-xs text-muted-foreground">
					<span>Status: {job?.status || "starting"}</span>
					<span>{pct}%</span>
				</div>
			</div>
		</div>
	);
}

export function MigrateDialog({ open, onOpenChange }: MigrateDialogProps) {
	const helpCtx = useHelp();
	const [activeTab, setActiveTab] = useState<TabId>("export");
	const [activeJobIds, setActiveJobIds] = useState<Record<TabId, string | null>>({
		export: null,
		import: null,
		validate: null,
	});

	const currentJobId = activeJobIds[activeTab];
	const { data: job } = useMigrationJob(currentJobId);

	const handleJobStarted = (jobId: string) => {
		setActiveJobIds((prev) => ({ ...prev, [activeTab]: jobId }));
	};

	const handleReset = () => {
		setActiveJobIds((prev) => ({ ...prev, [activeTab]: null }));
	};

	const isTerminal = job?.status === "completed" || job?.status === "failed";

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="max-h-[calc(100vh-3rem)] overflow-y-auto sm:max-w-[760px]">
				<DialogHeader className="pr-8">
					<div className="flex items-start justify-between gap-4">
						<div className="space-y-1.5">
							<DialogTitle>Data migration</DialogTitle>
							<DialogDescription>
								Move registry records and telemetry between Observal instances. Validate artifacts before importing.
							</DialogDescription>
						</div>
						<Button type="button" variant="outline" size="sm" onClick={() => helpCtx.openHelp({ pageKey: "migration" })}>
							<HelpCircle className="h-3.5 w-3.5" />
							Guide
						</Button>
					</div>
				</DialogHeader>

				<Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as TabId)}>
					<TabsList className="grid w-full grid-cols-3">
						<TabsTrigger value="export">Export</TabsTrigger>
						<TabsTrigger value="import">Import</TabsTrigger>
						<TabsTrigger value="validate">Validate</TabsTrigger>
					</TabsList>

					<div className="mt-5 min-h-[280px]">
						{currentJobId && isTerminal && job ? (
							<MigrateJobResult job={job} onReset={handleReset} />
						) : currentJobId ? (
							<JobProgress job={job} />
						) : (
							<>
								<TabsContent value="export" className="mt-0">
									<MigrateExportForm onJobStarted={handleJobStarted} />
								</TabsContent>
								<TabsContent value="import" className="mt-0">
									<MigrateImportForm onJobStarted={handleJobStarted} />
								</TabsContent>
								<TabsContent value="validate" className="mt-0">
									<MigrateValidateForm onJobStarted={handleJobStarted} />
								</TabsContent>
							</>
						)}
					</div>
				</Tabs>
			</DialogContent>
		</Dialog>
	);
}
