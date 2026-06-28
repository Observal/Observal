// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useCurrentMigrationOrg, useStartMigrationImport } from "@/hooks/use-admin-api";
import type { MigrationScope } from "@/lib/types/admin";
import { ArtifactPicker, ScopeChoiceGroup } from "./migrate-form-fields";

interface MigrateImportFormProps {
	onJobStarted: (jobId: string) => void;
}

export function MigrateImportForm({ onJobStarted }: MigrateImportFormProps) {
	const [scope, setScope] = useState<MigrationScope>("both");
	const [files, setFiles] = useState<File[]>([]);
	const { data: orgInfo } = useCurrentMigrationOrg();
	const [orgId, setOrgId] = useState("");
	const [projectId, setProjectId] = useState("");
	const importMutation = useStartMigrationImport();

	const orgValue = orgId || orgInfo?.org_id || "";
	const projectValue = projectId || orgInfo?.project_id || "";

	const handleStart = () => {
		if (files.length === 0) return;

		const formData = new FormData();
		files.forEach((file) => formData.append("files", file));
		formData.append("scope", scope);
		if (orgValue) formData.append("org_id", orgValue);
		if (projectValue) formData.append("project_id", projectValue);

		importMutation.mutate(formData, {
			onSuccess: (data) => onJobStarted(data.job_id),
		});
	};

	return (
		<div className="space-y-5">
			<ArtifactPicker
				files={files}
				onChange={setFiles}
				description="Upload the registry archive, telemetry parquet files, or both. Validation should be run before import."
			/>

			<div className="space-y-2">
				<div>
					<label className="text-sm font-medium">What should be imported?</label>
					<p className="mt-1 text-xs text-muted-foreground">Match this to the artifacts you uploaded.</p>
				</div>
				<ScopeChoiceGroup name="import-scope" value={scope} onChange={setScope} />
			</div>

			<div className="grid gap-3 sm:grid-cols-2">
				<div className="space-y-1.5">
					<label className="text-xs font-medium">Target organization ID</label>
					<Input value={orgValue} onChange={(event) => setOrgId(event.target.value)} placeholder="Auto detected" className="h-8 text-xs" />
				</div>
				<div className="space-y-1.5">
					<label className="text-xs font-medium">Target project ID</label>
					<Input value={projectValue} onChange={(event) => setProjectId(event.target.value)} placeholder="Auto detected" className="h-8 text-xs" />
				</div>
			</div>

			<Button type="button" className="w-full" onClick={handleStart} disabled={importMutation.isPending || files.length === 0}>
				{importMutation.isPending ? "Starting import..." : "Start import"}
			</Button>
		</div>
	);
}
