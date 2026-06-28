// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { UploadCloud } from "lucide-react";
import type { ChangeEvent } from "react";
import { cn } from "@/lib/utils";
import type { MigrationScope } from "@/lib/types/admin";

type ScopeOption = {
	value: MigrationScope;
	title: string;
	description: string;
	disabled?: boolean;
	disabledReason?: string;
};

export const ALL_SCOPE_OPTIONS: ScopeOption[] = [
	{
		value: "postgres",
		title: "Registry data",
		description: "Users, agents, components, settings, reviews, and metadata.",
	},
	{
		value: "clickhouse",
		title: "Telemetry data",
		description: "Trace and span history stored in ClickHouse.",
	},
	{
		value: "both",
		title: "Registry + telemetry",
		description: "Use for a full instance move when both stores are available.",
	},
];

export function ScopeChoiceGroup({
	name,
	value,
	onChange,
	options = ALL_SCOPE_OPTIONS,
}: {
	name: string;
	value: MigrationScope;
	onChange: (value: MigrationScope) => void;
	options?: ScopeOption[];
}) {
	return (
		<div className={cn("grid gap-2", options.length === 2 ? "sm:grid-cols-2" : "sm:grid-cols-3")}>
			{options.map((option) => {
				const checked = value === option.value;
				return (
					<label
						key={option.value}
						className={cn(
							"relative rounded-md border bg-card p-3 text-left transition-colors",
							checked ? "border-primary bg-primary/5" : "border-border hover:border-primary/50",
							option.disabled && "cursor-not-allowed opacity-50 hover:border-border",
						)}
					>
						<input
							type="radio"
							name={name}
							value={option.value}
							checked={checked}
							disabled={option.disabled}
							onChange={() => onChange(option.value)}
							className="sr-only"
						/>
						<span className="block text-sm font-medium">{option.title}</span>
						<span className="mt-1 block text-xs leading-5 text-muted-foreground">{option.description}</span>
						{option.disabledReason && (
							<span className="mt-2 block text-xs text-muted-foreground">{option.disabledReason}</span>
						)}
					</label>
				);
			})}
		</div>
	);
}

export function ArtifactPicker({
	files,
	onChange,
	description,
}: {
	files: File[];
	onChange: (files: File[]) => void;
	description: string;
}) {
	const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
		onChange(Array.from(event.target.files ?? []));
	};

	return (
		<label className="block rounded-md border border-dashed border-border bg-muted/20 p-4 transition-colors hover:border-primary/50 hover:bg-muted/30">
			<input type="file" multiple accept=".tar.gz,.gz,.parquet" onChange={handleChange} className="sr-only" />
			<div className="flex items-start gap-3">
				<div className="rounded-md border border-border bg-background p-2">
					<UploadCloud className="h-4 w-4 text-muted-foreground" />
				</div>
				<div className="min-w-0 flex-1">
					<p className="text-sm font-medium">Choose migration artifacts</p>
					<p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p>
					{files.length > 0 && (
						<p className="mt-2 truncate text-xs font-medium text-foreground">
							{files.length === 1 ? files[0]?.name : `${files.length} files selected`}
						</p>
					)}
				</div>
			</div>
		</label>
	);
}
