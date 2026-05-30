// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Tanvi Reddy <reddyplayer22@gmail.com>
// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useState, useCallback, useSyncExternalStore } from "react";
import { useTheme } from "@/lib/theme";
import { Check, Loader2 } from "lucide-react";
import { toast } from "sonner";
import {
	getUserName,
	getUserEmail,
	getUserRole,
	getUserUsername,
	getUserAvatar,
	setUserUsername,
	auth,
} from "@/lib/api";
import { ROLE_LABELS, type Role } from "@/hooks/use-role-guard";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/layouts/page-header";
import { AvatarEditable } from "@/components/account/avatar-upload";

// ── Theme definitions ──────────────────────────────────────────────────────
// Swatches: [bg, accent, fg] in oklch — derived from globals.css
const THEMES = [
	{
		value: "light",
		label: "Light",
		swatches: [
			"oklch(0.99 0.005 260)",
			"oklch(0.5 0.2 270)",
			"oklch(0.15 0.02 260)",
		],
	},
	{
		value: "solarized-light",
		label: "Solarized Light",
		swatches: [
			"oklch(0.97 0.026 90)",
			"oklch(0.61 0.139 245)",
			"oklch(0.52 0.028 219)",
		],
	},
	{
		value: "dark",
		label: "Dark",
		swatches: [
			"oklch(0.13 0.02 260)",
			"oklch(0.62 0.18 270)",
			"oklch(0.88 0.01 260)",
		],
	},
	{
		value: "midnight",
		label: "Midnight",
		swatches: [
			"oklch(0.1 0.025 270)",
			"oklch(0.6 0.2 275)",
			"oklch(0.88 0.008 260)",
		],
	},
	{
		value: "forest",
		label: "Forest",
		swatches: [
			"oklch(0.1 0.02 155)",
			"oklch(0.6 0.15 155)",
			"oklch(0.87 0.01 150)",
		],
	},
	{
		value: "sunset",
		label: "Sunset",
		swatches: [
			"oklch(0.11 0.025 45)",
			"oklch(0.7 0.15 60)",
			"oklch(0.87 0.01 50)",
		],
	},
	{
		value: "solarized-dark",
		label: "Solarized Dark",
		swatches: [
			"oklch(0.27 0.049 220)",
			"oklch(0.61 0.139 245)",
			"oklch(0.65 0.020 205)",
		],
	},
	{
		value: "dracula",
		label: "Dracula",
		swatches: [
			"oklch(0.26 0.030 278)",
			"oklch(0.74 0.149 302)",
			"oklch(0.98 0.008 107)",
		],
	},
	{
		value: "nord",
		label: "Nord",
		swatches: [
			"oklch(0.30 0.018 230)",
			"oklch(0.78 0.065 205)",
			"oklch(0.93 0.010 230)",
		],
	},
	{
		value: "monokai",
		label: "Monokai",
		swatches: [
			"oklch(0.25 0.012 110)",
			"oklch(0.84 0.20 128)",
			"oklch(0.98 0.008 107)",
		],
	},
	{
		value: "gruvbox",
		label: "Gruvbox",
		swatches: [
			"oklch(0.28 0.000 90)",
			"oklch(0.73 0.182 52)",
			"oklch(0.88 0.055 85)",
		],
	},
	{
		value: "catppuccin",
		label: "Catppuccin",
		swatches: [
			"oklch(0.22 0.035 290)",
			"oklch(0.72 0.14 305)",
			"oklch(0.86 0.045 270)",
		],
	},
	{
		value: "tokyo-night",
		label: "Tokyo Night",
		swatches: [
			"oklch(0.20 0.025 260)",
			"oklch(0.68 0.15 260)",
			"oklch(0.76 0.050 268)",
		],
	},
	{
		value: "one-dark",
		label: "One Dark",
		swatches: [
			"oklch(0.27 0.012 240)",
			"oklch(0.70 0.13 240)",
			"oklch(0.78 0.018 250)",
		],
	},
	{
		value: "rose-pine",
		label: "Rosé Pine",
		swatches: [
			"oklch(0.19 0.030 300)",
			"oklch(0.74 0.10 305)",
			"oklch(0.90 0.028 295)",
		],
	},
] as const;

// ── localStorage sync helpers ──────────────────────────────────────────────
function subscribe(cb: () => void) {
	window.addEventListener("storage", cb);
	return () => window.removeEventListener("storage", cb);
}

function getNameSnapshot() {
	if (typeof window === "undefined") return "";
	return getUserName() ?? "";
}

function getEmailSnapshot() {
	if (typeof window === "undefined") return "";
	return getUserEmail() ?? "";
}

function getRoleSnapshot() {
	if (typeof window === "undefined") return "";
	return getUserRole() ?? "";
}

function getServerSnapshot() {
	return "";
}

function initials(name: string) {
	return name
		.split(" ")
		.map((w) => w[0])
		.join("")
		.toUpperCase()
		.slice(0, 2);
}

// ── Change Username ───────────────────────────────────────────────────────
function ChangeUsernameSection() {
	const [newUsername, setNewUsername] = useState("");
	const [saving, setSaving] = useState(false);
	const currentUsername = useSyncExternalStore(
		(cb) => {
			window.addEventListener("storage", cb);
			return () => window.removeEventListener("storage", cb);
		},
		() => getUserUsername() ?? "",
		() => "",
	);

	const handleSubmit = useCallback(async () => {
		if (!newUsername.trim()) {
			toast.error("Username cannot be empty");
			return;
		}
		if (newUsername.length < 3) {
			toast.error("Username must be at least 3 characters");
			return;
		}
		if (newUsername.length > 32) {
			toast.error("Username must be at most 32 characters");
			return;
		}
		if (!/^[a-z0-9][a-z0-9\-]{1,30}[a-z0-9]$/.test(newUsername)) {
			toast.error(
				"Username must be lowercase alphanumeric with hyphens (3-32 chars, start/end with alphanumeric)",
			);
			return;
		}
		if (newUsername === currentUsername) {
			toast.error("New username is the same as current username");
			return;
		}

		setSaving(true);
		try {
			const res = await fetch("/api/v1/auth/profile/username", {
				method: "PUT",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${sessionStorage.getItem("observal_access_token")}`,
				},
				body: JSON.stringify({ username: newUsername }),
			});
			if (!res.ok) {
				const err = await res.json();
				throw new Error(err.detail || "Failed to update username");
			}
			const data = await res.json();
			setUserUsername(data.username);
			toast.success("Username updated successfully");
			setNewUsername("");
		} catch (e) {
			toast.error(e instanceof Error ? e.message : "Failed to update username");
		} finally {
			setSaving(false);
		}
	}, [newUsername, currentUsername]);

	return (
		<section className="animate-in stagger-0">
			<h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
				Change Username
			</h3>
			<Card>
				<CardContent className="p-4 space-y-3">
					<div>
						<label className="text-xs text-muted-foreground mb-1 block">
							Current Username
						</label>
						<Input
							type="text"
							value={currentUsername || "—"}
							disabled
							className="h-8 text-sm bg-muted"
						/>
					</div>
					<div>
						<label className="text-xs text-muted-foreground mb-1 block">
							New Username
						</label>
						<Input
							type="text"
							value={newUsername}
							onChange={(e) => setNewUsername(e.target.value.toLowerCase())}
							className="h-8 text-sm"
							placeholder="3-32 chars, lowercase alphanumeric + hyphens"
							onKeyDown={(e) => {
								if (e.key === "Enter") handleSubmit();
							}}
						/>
						<p className="text-xs text-muted-foreground mt-1.5">
							Must be 3-32 characters, lowercase alphanumeric and hyphens only.
							Must start and end with alphanumeric.
						</p>
					</div>
					<Button
						size="sm"
						className="h-8"
						onClick={handleSubmit}
						disabled={
							saving || !newUsername.trim() || newUsername === currentUsername
						}
					>
						{saving ? (
							<Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
						) : null}
						Update Username
					</Button>
				</CardContent>
			</Card>
		</section>
	);
}

// ── Password strength helpers ────────────────────────────────────────────
const PASSWORD_RULES = [
	{
		id: "len",
		label: "At least 12 characters",
		test: (p: string) => p.length >= 12,
	},
	{
		id: "upper",
		label: "One uppercase letter",
		test: (p: string) => /[A-Z]/.test(p),
	},
	{ id: "digit", label: "One number", test: (p: string) => /[0-9]/.test(p) },
	{
		id: "special",
		label: "One special character",
		test: (p: string) => /[^A-Za-z0-9]/.test(p),
	},
];

function passwordIsStrong(p: string) {
	return PASSWORD_RULES.every((r) => r.test(p));
}

// ── Change Password ───────────────────────────────────────────────────────
function ChangePasswordSection() {
	const [currentPassword, setCurrentPassword] = useState("");
	const [newPassword, setNewPassword] = useState("");
	const [confirmPassword, setConfirmPassword] = useState("");
	const [saving, setSaving] = useState(false);
	const [touched, setTouched] = useState(false);

	const strong = passwordIsStrong(newPassword);
	const matches = newPassword === confirmPassword;
	const canSubmit = currentPassword && strong && matches && confirmPassword;

	const handleSubmit = useCallback(async () => {
		if (!strong) {
			toast.error("Password does not meet the requirements");
			return;
		}
		if (!matches) {
			toast.error("Passwords do not match");
			return;
		}
		setSaving(true);
		try {
			await auth.changePassword({
				current_password: currentPassword,
				new_password: newPassword,
			});
			toast.success("Password changed successfully");
			setCurrentPassword("");
			setNewPassword("");
			setConfirmPassword("");
			setTouched(false);
		} catch (e) {
			toast.error(e instanceof Error ? e.message : "Failed to change password");
		} finally {
			setSaving(false);
		}
	}, [currentPassword, newPassword, confirmPassword, strong, matches]);

	return (
		<section className="animate-in stagger-1">
			<h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
				Change Password
			</h3>
			<Card>
				<CardContent className="p-4 space-y-3">
					<div>
						<label className="text-xs text-muted-foreground mb-1 block">
							Current Password
						</label>
						<Input
							type="password"
							value={currentPassword}
							onChange={(e) => setCurrentPassword(e.target.value)}
							className="h-8 text-sm"
							placeholder="Enter current password"
						/>
					</div>
					<div>
						<label className="text-xs text-muted-foreground mb-1 block">
							New Password
						</label>
						<Input
							type="password"
							value={newPassword}
							onChange={(e) => {
								setNewPassword(e.target.value);
								setTouched(true);
							}}
							className={`h-8 text-sm ${
								touched && newPassword
									? strong
										? "border-green-500 focus-visible:ring-green-500"
										: "border-destructive focus-visible:ring-destructive"
									: ""
							}`}
							placeholder="At least 12 characters"
						/>
						{/* Requirements checklist — shown once user starts typing */}
						{touched && newPassword && (
							<ul className="mt-2 space-y-1">
								{PASSWORD_RULES.map((rule) => {
									const ok = rule.test(newPassword);
									return (
										<li
											key={rule.id}
											className={`flex items-center gap-1.5 text-xs ${
												ok
													? "text-green-600 dark:text-green-400"
													: "text-muted-foreground"
											}`}
										>
											<span>{ok ? "✓" : "○"}</span>
											{rule.label}
										</li>
									);
								})}
							</ul>
						)}
					</div>
					<div>
						<label className="text-xs text-muted-foreground mb-1 block">
							Confirm New Password
						</label>
						<Input
							type="password"
							value={confirmPassword}
							onChange={(e) => setConfirmPassword(e.target.value)}
							className={`h-8 text-sm ${
								confirmPassword
									? matches
										? "border-green-500 focus-visible:ring-green-500"
										: "border-destructive focus-visible:ring-destructive"
									: ""
							}`}
							placeholder="Re-enter new password"
							onKeyDown={(e) => {
								if (e.key === "Enter") handleSubmit();
							}}
						/>
						{confirmPassword && !matches && (
							<p className="text-xs text-destructive mt-1">
								Passwords do not match
							</p>
						)}
					</div>
					<Button
						size="sm"
						className="h-8"
						onClick={handleSubmit}
						disabled={saving || !canSubmit}
					>
						{saving ? (
							<Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
						) : null}
						Update Password
					</Button>
				</CardContent>
			</Card>
		</section>
	);
}

function getUsernameSnapshot() {
	if (typeof window === "undefined") return "";
	return getUserUsername() ?? "";
}

// ── Page ───────────────────────────────────────────────────────────────────
function getAvatarSnapshot() {
	if (typeof window === "undefined") return null;
	return getUserAvatar();
}

export default function AccountPage() {
	const name = useSyncExternalStore(
		subscribe,
		getNameSnapshot,
		getServerSnapshot,
	);
	const email = useSyncExternalStore(
		subscribe,
		getEmailSnapshot,
		getServerSnapshot,
	);
	const role = useSyncExternalStore(
		subscribe,
		getRoleSnapshot,
		getServerSnapshot,
	);
	const username = useSyncExternalStore(
		subscribe,
		getUsernameSnapshot,
		getServerSnapshot,
	);
	const avatar = useSyncExternalStore(
		subscribe,
		getAvatarSnapshot,
		() => null as string | null,
	);

	const { theme, setTheme } = useTheme();

	const displayName = name || "—";
	const displayEmail = email || "—";
	const roleLabel = role ? (ROLE_LABELS[role as Role] ?? role) : "—";

	return (
		<>
			<PageHeader title="Account" />
			<div className="p-6 w-full mx-auto max-w-2xl space-y-6">
				{/* ── Section 1: Profile ─────────────────────────────────────────── */}
				<section className="animate-in">
					<h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
						Profile
					</h3>
					<Card>
						<CardContent className="p-4 space-y-3">
							<div className="flex items-center gap-4">
								<AvatarEditable name={displayName} avatarUrl={avatar} />
								<div className="min-w-0 flex-1">
									<p className="text-sm font-semibold truncate">
										{displayName}
									</p>
									<p className="text-xs text-muted-foreground truncate mt-0.5">
										{displayEmail}
									</p>
								</div>
								<Badge variant="secondary" className="shrink-0 text-xs">
									{roleLabel}
								</Badge>
							</div>
							{username && (
								<div className="flex items-center gap-2">
									<p className="text-xs text-muted-foreground">Username:</p>
									<p className="text-sm font-mono">@{username}</p>
								</div>
							)}
						</CardContent>
					</Card>
				</section>

				{/* ── Section 2: Change Username ───────────────────────────────── */}
				<ChangeUsernameSection />

				{/* ── Section 3: Change Password ───────────────────────────────── */}
				<ChangePasswordSection />

				{/* ── Section 4: Theme ───────────────────────────────────────────── */}
				<section className="animate-in stagger-1">
					<h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
						Theme
					</h3>
					<div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
						{THEMES.map((t) => {
							const isActive = theme === t.value;
							return (
								<button
									key={t.value}
									type="button"
									onClick={() => setTheme(t.value)}
									className={
										"rounded-md border p-3 text-left transition-colors hover:bg-accent/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" +
										(isActive
											? " border-primary-accent bg-accent/20"
											: " border-border bg-card")
									}
								>
									{/* Color preview: 3 stacked bars */}
									<div className="rounded overflow-hidden mb-2.5 h-8 flex flex-col gap-px">
										{t.swatches.map((color, i) => (
											<div
												key={i}
												className="flex-1"
												style={{ backgroundColor: color }}
											/>
										))}
									</div>
									<div className="flex items-center justify-between">
										<span className="text-xs font-medium">{t.label}</span>
										{isActive && (
											<Check className="h-3 w-3 text-primary-accent" />
										)}
									</div>
								</button>
							);
						})}
					</div>
				</section>
			</div>
		</>
	);
}
