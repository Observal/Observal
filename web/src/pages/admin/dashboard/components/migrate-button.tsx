// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useState } from "react";
import { ArrowLeftRight } from "lucide-react";
import { useWhoami } from "@/hooks/use-admin-api";
import { MigrateDialog } from "./migrate-dialog";

export function MigrateButton() {
	const { data: user } = useWhoami();
	const [open, setOpen] = useState(false);

	// Only show for super_admin
	if (user?.role !== "super_admin") return null;

	return (
		<>
			<button
				onClick={() => setOpen(true)}
				className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-border hover:bg-muted/50 transition-colors"
			>
				<ArrowLeftRight className="h-3 w-3" />
				Migrate
			</button>
			<MigrateDialog open={open} onOpenChange={setOpen} />
		</>
	);
}
