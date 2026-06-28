// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useStartMigrationValidate } from "@/hooks/use-admin-api";
import type { MigrationScope } from "@/lib/types/admin";
import { ArtifactPicker, ScopeChoiceGroup } from "./migrate-form-fields";

interface MigrateValidateFormProps {
	onJobStarted: (jobId: string) => void;
}

export function MigrateValidateForm({ onJobStarted }: MigrateValidateFormProps) {
	const [scope, setScope] = useState<MigrationScope>("both");
	const [files, setFiles] = useState<File[]>([]);
	const validateMutation = useStartMigrationValidate();

	const handleStart = () => {
		if (files.length === 0) return;

		const formData = new FormData();
		files.forEach((file) => formData.append("files", file));
		formData.append("scope", scope);

		validateMutation.mutate(formData, {
			onSuccess: (data) => onJobStarted(data.job_id),
		});
	};

	return (
		<div className="space-y-5">
			<ArtifactPicker
				files={files}
				onChange={setFiles}
				description="Validate checksums, table counts, and telemetry references before importing into a target instance."
			/>

			<div className="space-y-2">
				<div>
					<label className="text-sm font-medium">What should be validated?</label>
					<p className="mt-1 text-xs text-muted-foreground">Use the same scope you plan to import.</p>
				</div>
				<ScopeChoiceGroup name="validate-scope" value={scope} onChange={setScope} />
			</div>

			<Button type="button" className="w-full" onClick={handleStart} disabled={validateMutation.isPending || files.length === 0}>
				{validateMutation.isPending ? "Starting validation..." : "Start validation"}
			</Button>
		</div>
	);
}
