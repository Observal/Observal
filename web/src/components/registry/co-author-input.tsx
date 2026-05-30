// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useState, useCallback } from "react";
import { X, Plus, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";

const API = "/api/v1";

function getAccessToken(): string | null {
	if (typeof window === "undefined") return null;
	return sessionStorage.getItem("observal_access_token");
}

export interface CoAuthor {
	id: string;
	email: string;
	username?: string | null;
	is_active?: boolean;
}

interface CoAuthorInputProps {
	/** Entity type: "agents" | "mcps" | "hooks" | "sandboxes" | "prompts" */
	entityType: string;
	/** UUID of the entity */
	entityId: string;
	/** Current co-authors list */
	coAuthors: CoAuthor[];
	/** Callback when list changes */
	onChange: (coAuthors: CoAuthor[]) => void;
	/** Whether the current user can manage co-authors */
	canManage?: boolean;
}

export function CoAuthorInput({
	entityType,
	entityId,
	coAuthors,
	onChange,
	canManage = true,
}: CoAuthorInputProps) {
	const [input, setInput] = useState("");
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);

	// Confirmation dialog state
	const [confirmAdd, setConfirmAdd] = useState<string | null>(null);
	const [confirmRemove, setConfirmRemove] = useState<CoAuthor | null>(null);

	const executeAdd = useCallback(async (value: string) => {
		setLoading(true);
		setError(null);

		try {
			const headers: Record<string, string> = {
				"Content-Type": "application/json",
			};
			const token = getAccessToken();
			if (token) headers["Authorization"] = `Bearer ${token}`;

			const isEmail = value.includes("@") && !value.startsWith("@") && value.indexOf("@") < value.length - 1;
			const body = isEmail
				? { email: value.toLowerCase() }
				: { username: value.replace(/^@/, "") };

			const res = await fetch(
				`${API}/${entityType}/${entityId}/co-authors`,
				{
					method: "POST",
					headers,
					body: JSON.stringify(body),
				},
			);

			if (!res.ok) {
				const data = await res.json().catch(() => ({}));
				setError(data.detail || `Failed to add co-author (${res.status})`);
				return;
			}

			const added: CoAuthor = await res.json();
			onChange([...coAuthors, added]);
			setInput("");
		} catch {
			setError("Network error");
		} finally {
			setLoading(false);
			setConfirmAdd(null);
		}
	}, [entityType, entityId, coAuthors, onChange]);

	const executeRemove = useCallback(
		async (userId: string) => {
			setLoading(true);
			setError(null);

			try {
				const headers: Record<string, string> = {};
				const token = getAccessToken();
				if (token) headers["Authorization"] = `Bearer ${token}`;

				const res = await fetch(
					`${API}/${entityType}/${entityId}/co-authors/${userId}`,
					{
						method: "DELETE",
						headers,
					},
				);

				if (!res.ok) {
					const data = await res.json().catch(() => ({}));
					setError(
						data.detail || `Failed to remove co-author (${res.status})`,
					);
					return;
				}

				onChange(coAuthors.filter((c) => c.id !== userId));
			} catch {
				setError("Network error");
			} finally {
				setLoading(false);
				setConfirmRemove(null);
			}
		},
		[entityType, entityId, coAuthors, onChange],
	);

	const handleAdd = () => {
		const value = input.trim();
		if (!value) return;
		setConfirmAdd(value);
	};

	const handleKeyDown = (e: React.KeyboardEvent) => {
		if (e.key === "Enter") {
			e.preventDefault();
			handleAdd();
		}
	};

	return (
		<div className="space-y-2">
			<Label>Co-Authors</Label>

			{/* Current co-authors */}
			{coAuthors.length > 0 && (
				<div className="flex flex-wrap gap-2">
					{coAuthors.map((author) => (
						<Badge
							key={author.id}
							variant="secondary"
							className="flex items-center gap-1 py-1 px-2"
						>
							<span className="text-xs">
								{author.username || author.email}
							</span>
							{canManage && (
								<button
									type="button"
									onClick={() => setConfirmRemove(author)}
									className="ml-1 rounded-full hover:bg-muted-foreground/20 p-0.5"
									disabled={loading}
								>
									<X className="h-3 w-3" />
								</button>
							)}
						</Badge>
					))}
				</div>
			)}

			{coAuthors.length === 0 && !canManage && (
				<p className="text-xs text-muted-foreground">No co-authors</p>
			)}

			{/* Add input */}
			{canManage && (
				<div className="flex gap-2">
					<Input
						placeholder="Email or username"
						value={input}
						onChange={(e) => {
							setInput(e.target.value);
							setError(null);
						}}
						onKeyDown={handleKeyDown}
						disabled={loading}
						className="flex-1"
					/>
					<Button
						type="button"
						variant="outline"
						size="sm"
						onClick={handleAdd}
						disabled={loading || !input.trim()}
					>
						{loading ? (
							<Loader2 className="h-4 w-4 animate-spin" />
						) : (
							<Plus className="h-4 w-4" />
						)}
					</Button>
				</div>
			)}

			{error && <p className="text-xs text-destructive">{error}</p>}

			{/* Add confirmation dialog */}
			<Dialog open={!!confirmAdd} onOpenChange={(open) => { if (!open) setConfirmAdd(null); }}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>Add co-author</DialogTitle>
						<DialogDescription>
							Are you sure you want to add <span className="font-medium text-foreground">{confirmAdd}</span> as a co-author? They will have full edit and publish access.
						</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<Button variant="outline" onClick={() => setConfirmAdd(null)} disabled={loading}>
							Cancel
						</Button>
						<Button onClick={() => confirmAdd && executeAdd(confirmAdd)} disabled={loading}>
							{loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
							Confirm
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>

			{/* Remove confirmation dialog */}
			<Dialog open={!!confirmRemove} onOpenChange={(open) => { if (!open) setConfirmRemove(null); }}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>Remove co-author</DialogTitle>
						<DialogDescription>
							Remove <span className="font-medium text-foreground">{confirmRemove?.username || confirmRemove?.email}</span> as a co-author? They will lose edit and publish access immediately.
						</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<Button variant="outline" onClick={() => setConfirmRemove(null)} disabled={loading}>
							Cancel
						</Button>
						<Button variant="destructive" onClick={() => confirmRemove && executeRemove(confirmRemove.id)} disabled={loading}>
							{loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
							Remove
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}
