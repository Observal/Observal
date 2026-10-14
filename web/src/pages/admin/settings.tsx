// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-License-Identifier: Apache-2.0


import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { Link } from "@tanstack/react-router";
import {
	Settings,
	Pencil,
	Trash2,
	Save,
	X,
	Loader2,
	Database,
	Activity,
	Shield,
	HelpCircle,
	Eye,
	FlaskConical,
	Upload,
	RotateCcw,
	Palette,
	AlertTriangle,
	ShieldAlert,
	ArrowLeftRight,
	Power,
	PanelLeft,
	ArrowLeft,
	ArrowUpRight,
	Search,
} from "lucide-react";
import { InsightsSection } from "./settings/insights-section";
import { UsagePingSection } from "./settings/usage-ping-section";
import { MigrateDialog } from "./dashboard/components/migrate-dialog";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { useHelp } from "@/components/wiki/help-context";
import { SETTING_DOCS, SECTION_DOCS } from "@/lib/docs-map";
import { useAdminSettings, useAdminSettingsSchema, useRestartApi, useRestartStatus, useSystemWarnings } from "@/hooks/use-api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import { useHarnesses } from "@/hooks/use-harnesses";
import { LEADERBOARD_DEPRECATION_NOTICE } from "@/lib/leaderboard";
import { useRoleGuard, hasMinRole } from "@/hooks/use-role-guard";
import type { AdminSetting, AdminSettingDef, AdminSettingSection, SystemWarning } from "@/lib/types";
import { admin, getUserRole } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
	DialogDescription,
	DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { PickerSelect } from "@/components/ui/picker-select";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";

// Sensitive keys that should never be displayed in plaintext.
// The server enforces this too (returns **REDACTED** for these keys),
// but we keep the set here for UI affordances (revoke button, write-only input).
const SENSITIVE_KEYS = new Set([
	"insights.api_key",
	"oauth.client_secret",
	"saml.idp_x509_cert",
	"saml.sp_key_encryption_password",
]);

const REDACTED_VALUE = "**REDACTED**";

// Settings with their own switch above; keep them out of the generic editors.
const DEDICATED_TOGGLE_KEYS = new Set([
	"deployment.public_registry_enabled",
	"deployment.leaderboard_enabled",
]);

const ALLOWED_LOGO_TYPES = [
	"image/png",
	"image/svg+xml",
	"image/x-icon",
	"image/vnd.microsoft.icon",
	"image/jpeg",
	"image/webp",
];
const MAX_LOGO_SIZE = 2 * 1024 * 1024;

const CATEGORIES = [
	{ id: "general", label: "Identity & access", description: "Branding, public access, trace visibility and usage reporting", icon: Palette },
	{ id: "insights", label: "Agent Insights", description: "Provider, models and report generation", icon: Activity },
	{ id: "data", label: "Data & runtime", description: "Retention, migration and resource limits", icon: Database },
	{ id: "platform", label: "Platform", description: "Discovery, registry, tokens and observability", icon: Settings },
	{ id: "security", label: "Security & deployment", description: "Authentication, deployment and destructive actions", icon: ShieldAlert },
];

const SECTION_CATEGORY: Record<string, string> = {
	appearance: "general", experimental: "general", access: "general", usage: "general", insights: "insights",
	migration: "data", retention: "data", data: "data", resource: "data", observability: "data",
	discovery: "platform", registry: "platform", jwt: "platform", misc: "platform",
	auth: "security", deployment: "security", security: "security", danger: "security",
};

const SECTION_ICONS: Record<string, React.ReactNode> = {
	insights: <Activity className="h-3.5 w-3.5" />,
	danger: <AlertTriangle className="h-3.5 w-3.5" />,
	deployment: <Shield className="h-3.5 w-3.5" />,
	security: <ShieldAlert className="h-3.5 w-3.5" />,
	sso: <Shield className="h-3.5 w-3.5" />,
	jwt: <Shield className="h-3.5 w-3.5" />,
	resource: <Database className="h-3.5 w-3.5" />,
	data: <Database className="h-3.5 w-3.5" />,
	observability: <Activity className="h-3.5 w-3.5" />,
	misc: <Settings className="h-3.5 w-3.5" />,
};

function sectionIcon(section: AdminSettingSection) {
	return SECTION_ICONS[section.id] ?? <Settings className="h-3.5 w-3.5" />;
}


function splitHarnessList(value: string): string[] {
	return value
		.split(",")
		.map((item) => item.trim())
		.filter(Boolean);
}

function joinHarnessList(values: string[]): string {
	return Array.from(new Set(values)).join(",");
}

function getHarnessLabel(harnesses: { name: string; display_name: string }[], value: string): string {
	return harnesses.find((harness) => harness.name === value)?.display_name ?? value;
}

function HarnessAllowlistEditor({
	value,
	onChange,
	harnesses,
}: {
	value: string;
	onChange: (value: string) => void;
	harnesses: { name: string; display_name: string }[];
}) {
	const selected = splitHarnessList(value);
	const available = harnesses.filter((harness) => !selected.includes(harness.name));

	const addHarness = (harness: string) => {
		const next = harness.trim();
		if (!next) return;
		onChange(joinHarnessList([...selected, next]));
	};

	const removeHarness = (harness: string) => {
		onChange(joinHarnessList(selected.filter((item) => item !== harness)));
	};

	return (
		<div className="flex-1 space-y-2">
			<div className="flex min-h-8 flex-wrap items-center gap-1.5 rounded-md border border-input bg-background px-2 py-1">
				{selected.length === 0 ? (
					<span className="text-xs text-muted-foreground">All supported harnesses</span>
				) : (
					selected.map((harness) => (
						<span key={harness} className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-xs text-foreground">
							{getHarnessLabel(harnesses, harness)}
							<button type="button" className="text-muted-foreground hover:text-foreground" onClick={() => removeHarness(harness)}>
								<X className="h-3 w-3" />
							</button>
						</span>
					))
				)}
			</div>
			<div className="flex items-center gap-2">
				<PickerSelect
					value=""
					onValueChange={addHarness}
					placeholder={selected.length === 0 ? "Restrict to specific harnesses" : "Add harness"}
					className="flex-1"
					inputClassName="h-8 text-sm"
					emptyLabel="All listed harnesses selected"
					options={available.map((harness) => ({ value: harness.name, label: harness.display_name }))}
				/>
				{selected.length > 0 && (
					<Button type="button" variant="ghost" size="sm" className="h-8" onClick={() => onChange("")}>Allow all</Button>
				)}
			</div>
		</div>
	);
}

function BoolSettingCard({ def, value, onToggle, helpClass, openHelp }: { def: AdminSettingDef; value: boolean; onToggle: (checked: boolean) => Promise<void>; helpClass: string; openHelp: (key?: string) => boolean }) {
	const [busy, setBusy] = useState(false);
	return (
		<div className={`rounded-md border-2 border-border bg-card p-3 relative ${helpClass}`}>
			<SettingHelpIcon settingKey={def.key} openHelp={openHelp} />
			<div className="flex items-start justify-between gap-3 pr-6">
				<div className="min-w-0">
					<div className="flex items-center gap-2"><span className="text-sm font-semibold text-foreground">{def.label}</span>{def.restart_required && <RestartRequiredMark />}</div>
					{def.subtitle && <p className="mt-1 text-xs text-foreground/60">{def.subtitle}</p>}
				</div>
				<Switch
					checked={value}
					disabled={busy}
					aria-label={def.label}
					onCheckedChange={async (checked) => { setBusy(true); try { await onToggle(checked); } finally { setBusy(false); } }}
				/>
			</div>
		</div>
	);
}

function RestartRequiredMark() {
	return (
		<span
			className="inline-flex items-center gap-1 text-[11px] font-normal text-muted-foreground"
			title="Changing this setting requires an API restart"
		>
			<Power className="h-3 w-3" aria-hidden="true" />
			Restart
		</span>
	);
}

function SettingHelpIcon({ settingKey, openHelp }: { settingKey: string; openHelp: (key?: string) => boolean }) {
	if (!SETTING_DOCS[settingKey]) return null;
	return (
		<button
			type="button"
			className="absolute right-2 top-2 text-muted-foreground/40 transition-colors hover:text-foreground"
			onClick={(e) => {
				e.preventDefault();
				e.stopPropagation();
				openHelp(settingKey);
			}}
			aria-label="Open setting help"
		>
			<HelpCircle className="h-4.5 w-4.5" />
		</button>
	);
}

export default function SettingsPage() {
	const { ready } = useRoleGuard("super_admin");
	const queryClient = useQueryClient();
	const {
		data: settings,
		isLoading,
		isError,
		error,
		refetch,
	} = useAdminSettings();
	const { data: settingsSchema } = useAdminSettingsSchema();
	const { data: restartStatus, refetch: refetchRestartStatus } = useRestartStatus();
	const { data: systemWarnings } = useSystemWarnings();
	const { data: harnesses = [] } = useHarnesses();
	const {
		ssoEnabled,
		samlEnabled,
		publicRegistryEnabled,
		experimentalReviewChecks,
		leaderboardEnabled,
		brandingLogo,
		brandingAppName,
		brandingWordmark,
	} = useDeploymentConfig();
	const [navQuery, setNavQuery] = useState("");
	const [searchFocused, setSearchFocused] = useState(false);
	const [activeCategory, setActiveCategory] = useState("home");
	const [editingKey, setEditingKey] = useState<string | null>(null);
	const [editingValue, setEditingValue] = useState("");
	const [revokeConfirmKey, setRevokeConfirmKey] = useState<string | null>(null);
	const [saving, setSaving] = useState(false);
	const [applyingResources, setApplyingResources] = useState(false);
	const [purgingTracesInsights, setPurgingTracesInsights] = useState(false);
	const [tracePrivacy, setTracePrivacy] = useState(false);
	const [tracePrivacyLoading, setTracePrivacyLoading] = useState(true);
	const [tracePrivacyToggling, setTracePrivacyToggling] = useState(false);
	const [publicRegistryToggling, setPublicRegistryToggling] = useState(false);
	const [reviewChecksToggling, setReviewChecksToggling] = useState(false);
	const [leaderboardToggling, setLeaderboardToggling] = useState(false);
	const [showLeaderboardConfirm, setShowLeaderboardConfirm] = useState(false);
	const [registeredAgentsOnly, setRegisteredAgentsOnly] = useState(false);
	const [registeredAgentsOnlyLoading, setRegisteredAgentsOnlyLoading] = useState(true);
	const [registeredAgentsOnlyToggling, setRegisteredAgentsOnlyToggling] =
		useState(false);
	const [retentionEnabled, setRetentionEnabled] = useState(false);
	const [retentionDays, setRetentionDays] = useState<string>("");
	const [scoreRetentionDays, setScoreRetentionDays] = useState<string>("");
	const [maxTraceCount, setMaxTraceCount] = useState<string>("");
	const [retentionGlobal, setRetentionGlobal] = useState(90);
	const [retentionLoading, setRetentionLoading] = useState(true);
	const [retentionSaving, setRetentionSaving] = useState(false);
	const [showRetentionConfirm, setShowRetentionConfirm] = useState(false);
	const [retentionConfirmChecked, setRetentionConfirmChecked] = useState(false);
	const [retentionPreview, setRetentionPreview] = useState<Record<
		string,
		number | string
	> | null>(null);
	const retentionWasEnabled = useRef(false);
	const [logoOverride, setLogoOverride] = useState<string | null | undefined>(
		undefined,
	);
	const [wordmarkOverride, setWordmarkOverride] = useState<
		string | null | undefined
	>(undefined);
	const [appNameOverride, setAppNameOverride] = useState<string | undefined>(
		undefined,
	);
	const [brandingSaving, setBrandingSaving] = useState(false);
	const [migrateOpen, setMigrateOpen] = useState(false);
	const handleRestarted = useCallback(() => {
		refetchRestartStatus();
		refetch();
	}, [refetch, refetchRestartStatus]);
	const { restarting, restartApi } = useRestartApi(handleRestarted);
	const fileInputRef = useRef<HTMLInputElement>(null);
	const wordmarkInputRef = useRef<HTMLInputElement>(null);

	// Help mode: modifier key + click opens contextual docs (provided by HelpProvider)
	const { helpActive, openHelp: openHelpCtx } = useHelp();

	const logoPreview = logoOverride !== undefined ? logoOverride : brandingLogo;

	/** Open the help panel for a setting key or section title */
	const openHelp = useCallback((settingKey?: string, sectionTitle?: string) => {
		return openHelpCtx({ settingKey, sectionTitle });
	}, [openHelpCtx]);

	/** CSS class applied to setting cards that have docs, when help mode is active */
	const helpTargetClass = (key: string) =>
		helpActive && SETTING_DOCS[key]
			? "ring-2 ring-primary/60 cursor-help transition-shadow"
			: "";
	const sectionHelpHeadingClass = (sectionTitle: string) =>
		helpActive && SECTION_DOCS[sectionTitle]
			? "cursor-help ring-2 ring-primary/60 ring-offset-2 ring-offset-background rounded-sm"
			: "";
	const wordmarkPreview =
		wordmarkOverride !== undefined ? wordmarkOverride : brandingWordmark;
	const appNameDraft =
		appNameOverride !== undefined ? appNameOverride : brandingAppName || "";

	useEffect(() => {
		if (!ready) return;
		admin
			.getTracePrivacy()
			.then((res) => setTracePrivacy(res.trace_privacy))
			.catch(() => { toast.error("Failed to load trace privacy setting"); })
			.finally(() => setTracePrivacyLoading(false));
		admin
			.getRegisteredAgentsOnly()
			.then((res) => setRegisteredAgentsOnly(res.registered_agents_only))
			.catch(() => { toast.error("Failed to load registered-agents-only setting"); })
			.finally(() => setRegisteredAgentsOnlyLoading(false));
		admin
			.getRetention()
			.then((res) => {
				setRetentionEnabled(res.retention_enabled);
				retentionWasEnabled.current = res.retention_enabled;
				setRetentionDays(res.data_retention_days?.toString() || "");
				setScoreRetentionDays(res.score_retention_days?.toString() || "");
				setMaxTraceCount(res.max_trace_count?.toString() || "");
				setRetentionGlobal(res.global_retention_days);
			})
			.catch(() => { toast.error("Failed to load retention settings"); })
			.finally(() => setRetentionLoading(false));
	}, [ready]);

	const handlePurgeTracesInsights = useCallback(async () => {
		if (!window.confirm("Permanently delete all traces/session telemetry and insight reports for this deployment? This cannot be undone.")) {
			return;
		}
		setPurgingTracesInsights(true);
		try {
			const res = await admin.purgeTracesAndInsights();
			queryClient.invalidateQueries();
			toast.success(`Purged telemetry and insights (${res.deleted_reports ?? 0} reports removed)`);
		} catch (e) {
			toast.error(e instanceof Error ? e.message : "Failed to purge traces and insights");
		} finally {
			setPurgingTracesInsights(false);
		}
	}, [queryClient]);

	const handleTracePrivacyToggle = useCallback(async (checked: boolean) => {
		setTracePrivacyToggling(true);
		try {
			const res = await admin.setTracePrivacy(checked);
			setTracePrivacy(res.trace_privacy);
			toast.success(
				`Trace privacy ${res.trace_privacy ? "enabled" : "disabled"}`,
			);
		} catch (e) {
			toast.error(
				e instanceof Error ? e.message : "Failed to update trace privacy",
			);
		} finally {
			setTracePrivacyToggling(false);
		}
	}, []);

	const handleReviewChecksToggle = useCallback(async (checked: boolean) => {
		setReviewChecksToggling(true);
		try {
			await admin.updateSetting("experimental.review_checks", { value: checked ? "true" : "false" });
			await queryClient.invalidateQueries({ queryKey: ["config", "public"] });
			await refetch();
			toast.success(`Review checks ${checked ? "enabled" : "disabled"}`);
		} catch (e) {
			toast.error(e instanceof Error ? e.message : "Failed to update review checks");
		} finally {
			setReviewChecksToggling(false);
		}
	}, [queryClient, refetch]);

	const handlePublicRegistryToggle = useCallback(async (checked: boolean) => {
		setPublicRegistryToggling(true);
		try {
			await admin.updateSetting("deployment.public_registry_enabled", {
				value: checked ? "true" : "false",
			});
			await queryClient.invalidateQueries({ queryKey: ["config", "public"] });
			await refetch();
			toast.success(`Public registry access ${checked ? "enabled" : "disabled"}`);
		} catch (e) {
			toast.error(
				e instanceof Error ? e.message : "Failed to update public registry access",
			);
		} finally {
			setPublicRegistryToggling(false);
		}
	}, [queryClient, refetch]);

	const handleLeaderboardToggle = useCallback(async (checked: boolean) => {
		setLeaderboardToggling(true);
		try {
			await admin.updateSetting("deployment.leaderboard_enabled", {
				value: checked ? "true" : "false",
			});
			await queryClient.invalidateQueries({ queryKey: ["config", "public"] });
			await refetch();
			toast.success(`Leaderboard turned ${checked ? "on" : "off"}`);
		} catch (e) {
			toast.error(
				e instanceof Error ? e.message : "Failed to update leaderboard visibility",
			);
		} finally {
			setLeaderboardToggling(false);
		}
	}, [queryClient, refetch]);

	const handleRegisteredAgentsOnlyToggle = useCallback(
		async (checked: boolean) => {
			setRegisteredAgentsOnlyToggling(true);
			try {
				const res = await admin.setRegisteredAgentsOnly(checked);
				setRegisteredAgentsOnly(res.registered_agents_only);
				toast.success(
					`Registered Agent Files only ${res.registered_agents_only ? "enabled" : "disabled"}`,
				);
			} catch (e) {
				toast.error(
					e instanceof Error ? e.message : "Failed to update setting",
				);
			} finally {
				setRegisteredAgentsOnlyToggling(false);
			}
		},
		[],
	);

	const retentionErrors = useMemo(() => {
		const errors: {
			data_retention_days?: string;
			score_retention_days?: string;
			max_trace_count?: string;
			general?: string;
		} = {};
		const days = retentionDays ? parseInt(retentionDays, 10) : null;
		const scoreDays = scoreRetentionDays
			? parseInt(scoreRetentionDays, 10)
			: null;
		const maxCount = maxTraceCount ? parseInt(maxTraceCount, 10) : null;

		if (days !== null && !isNaN(days)) {
			if (days < 7) errors.data_retention_days = "Minimum 7 days";
			else if (retentionGlobal > 0 && days > retentionGlobal)
				errors.data_retention_days = `Cannot exceed global limit of ${retentionGlobal} days`;
		}
		if (scoreDays !== null && !isNaN(scoreDays)) {
			if (scoreDays < 7) errors.score_retention_days = "Minimum 7 days";
			else if (days && scoreDays < days)
				errors.score_retention_days = `Must be ≥ trace retention (${days} days)`;
		}
		if (maxCount !== null && !isNaN(maxCount)) {
			if (maxCount < 1000) errors.max_trace_count = "Minimum 1,000 traces";
		}
		if (retentionEnabled && !days && !maxCount) {
			errors.general = "Set at least one retention threshold to enable";
		}

		return errors;
	}, [
		retentionDays,
		scoreRetentionDays,
		maxTraceCount,
		retentionEnabled,
		retentionGlobal,
	]);

	const hasRetentionErrors = Object.keys(retentionErrors).length > 0;

	const handleRetentionSave = useCallback(async () => {
		const days = retentionDays ? parseInt(retentionDays, 10) : null;
		const scoreDays = scoreRetentionDays
			? parseInt(scoreRetentionDays, 10)
			: null;
		const maxCount = maxTraceCount ? parseInt(maxTraceCount, 10) : null;

		if (retentionEnabled && !retentionWasEnabled.current && days) {
			setShowRetentionConfirm(true);
			admin
				.previewRetention(days)
				.then(setRetentionPreview)
				.catch(() => setRetentionPreview(null));
			return;
		}

		setRetentionSaving(true);
		try {
			const res = await admin.setRetention({
				retention_enabled: retentionEnabled,
				data_retention_days: days,
				score_retention_days: scoreDays,
				max_trace_count: maxCount,
			});
			setRetentionEnabled(res.retention_enabled);
			retentionWasEnabled.current = res.retention_enabled;
			setRetentionDays(res.data_retention_days?.toString() || "");
			setScoreRetentionDays(res.score_retention_days?.toString() || "");
			setMaxTraceCount(res.max_trace_count?.toString() || "");
			queryClient.invalidateQueries({ queryKey: ["admin", "retention"] });
			toast.success("Retention settings updated");
		} catch (e) {
			toast.error(
				e instanceof Error ? e.message : "Failed to update retention",
			);
		} finally {
			setRetentionSaving(false);
		}
	}, [
		retentionEnabled,
		retentionDays,
		scoreRetentionDays,
		maxTraceCount,
		queryClient,
	]);

	const handleRetentionConfirm = useCallback(async () => {
		setShowRetentionConfirm(false);
		setRetentionConfirmChecked(false);
		setRetentionSaving(true);
		const days = retentionDays ? parseInt(retentionDays, 10) : null;
		const scoreDays = scoreRetentionDays
			? parseInt(scoreRetentionDays, 10)
			: null;
		const maxCount = maxTraceCount ? parseInt(maxTraceCount, 10) : null;
		try {
			const res = await admin.setRetention({
				retention_enabled: true,
				data_retention_days: days,
				score_retention_days: scoreDays,
				max_trace_count: maxCount,
			});
			setRetentionEnabled(res.retention_enabled);
			retentionWasEnabled.current = res.retention_enabled;
			setRetentionDays(res.data_retention_days?.toString() || "");
			setScoreRetentionDays(res.score_retention_days?.toString() || "");
			setMaxTraceCount(res.max_trace_count?.toString() || "");
			queryClient.invalidateQueries({ queryKey: ["admin", "retention"] });
			toast.success("Data retention enabled");
		} catch (e) {
			toast.error(
				e instanceof Error ? e.message : "Failed to enable retention",
			);
		} finally {
			setRetentionSaving(false);
			setRetentionPreview(null);
		}
	}, [retentionDays, scoreRetentionDays, maxTraceCount, queryClient]);

	const handleImageFile = useCallback(
		(file: File, setter: (v: string) => void) => {
			if (!ALLOWED_LOGO_TYPES.includes(file.type)) {
				toast.error("Unsupported file type. Use PNG, SVG, ICO, JPEG, or WEBP.");
				return;
			}
			if (file.size > MAX_LOGO_SIZE) {
				toast.error(
					`File too large (${Math.round(file.size / 1024)}KB). Maximum: 2MB.`,
				);
				return;
			}
			const reader = new FileReader();
			reader.onload = () => setter(reader.result as string);
			reader.readAsDataURL(file);
		},
		[],
	);

	const handleSaveBranding = useCallback(async () => {
		setBrandingSaving(true);
		try {
			if (logoPreview !== brandingLogo) {
				await admin.updateSetting("branding.logo", {
					value: logoPreview || "",
				});
			}
			if (wordmarkPreview !== brandingWordmark) {
				await admin.updateSetting("branding.wordmark", {
					value: wordmarkPreview || "",
				});
			}
			const trimmedName = appNameDraft.trim();
			if (trimmedName !== (brandingAppName || "")) {
				await admin.updateSetting("branding.app_name", { value: trimmedName });
			}
			setLogoOverride(undefined);
			setWordmarkOverride(undefined);
			setAppNameOverride(undefined);
			queryClient.invalidateQueries({ queryKey: ["config", "public"] });
			toast.success("Appearance updated");
		} catch (e) {
			toast.error(e instanceof Error ? e.message : "Failed to save appearance");
		} finally {
			setBrandingSaving(false);
		}
	}, [
		logoPreview,
		brandingLogo,
		wordmarkPreview,
		brandingWordmark,
		appNameDraft,
		brandingAppName,
		queryClient,
	]);

	const handleResetBranding = useCallback(async () => {
		setBrandingSaving(true);
		try {
			await admin.updateSetting("branding.logo", { value: "" });
			await admin.updateSetting("branding.wordmark", { value: "" });
			await admin.updateSetting("branding.app_name", { value: "" });
			setLogoOverride(undefined);
			setWordmarkOverride(undefined);
			setAppNameOverride(undefined);
			queryClient.invalidateQueries({ queryKey: ["config", "public"] });
			toast.success("Appearance reset to defaults");
		} catch (e) {
			toast.error(e instanceof Error ? e.message : "Failed to reset appearance");
		} finally {
			setBrandingSaving(false);
		}
	}, [queryClient]);

	const hasBrandingChanges =
		logoPreview !== brandingLogo ||
		wordmarkPreview !== brandingWordmark ||
		appNameDraft.trim() !== (brandingAppName || "");

	const entries = useMemo<AdminSetting[]>(() => (
		Array.isArray(settings)
			? settings
			: Object.entries(settings ?? {}).map(([key, value]) => ({ key, value: String(value) }))
	).filter((entry) => !entry.key.startsWith("branding.")), [settings]);

	const settingSections = useMemo(() => (settingsSchema ?? []).filter(
		(section) => section.id !== "sso" && section.id !== "usage_ping" && section.id !== "experimental",
	), [settingsSchema]);
	const categoryForSection = (id: string) => SECTION_CATEGORY[id] ??
		(settingSections.find((section) => section.id === id)?.danger ? "security" : "platform");
	const searchableSections = [
		{ id: "appearance", label: "Appearance", terms: "icon wordmark app name branding" },
		{ id: "experimental", label: "Experimental", terms: "review checks" },
		{ id: "access", label: "Access & privacy", terms: "public registry trace visibility registered agents sso saml" },
		{ id: "usage", label: "Usage reporting", terms: "company name reporting frequency send payload" },
		{ id: "insights", label: "Agent Insights", terms: "provider api key models batch processing" },
		{ id: "migration", label: "Data migration", terms: "export import validate" },
		{ id: "retention", label: "Data retention", terms: "trace retention score retention max trace count" },
		...settingSections.filter((section) => section.id !== "insights" && section.settings.some((setting) => setting.key !== "deployment.public_registry_enabled"))
			.map((section) => ({ id: section.id, label: section.title, terms: section.settings.map((setting) => `${setting.label} ${setting.key}`).join(" ") })),
	];
	const searchResults = navQuery.trim() ? searchableSections.filter((section) =>
		`${section.label} ${section.terms}`.toLowerCase().includes(navQuery.trim().toLowerCase())
	) : [];
	const goToCategory = (id: string) => {
		setActiveCategory(id);
		setNavQuery("");
		document.getElementById("settings-page")?.closest("main")?.scrollTo({ top: 0 });
	};
	const goToSection = (id: string) => {
		setActiveCategory(categoryForSection(id));
		setNavQuery("");
		requestAnimationFrame(() => {
			const target = document.getElementById(`settings-${id}`);
			if (target instanceof HTMLDetailsElement) target.open = true;
			target?.scrollIntoView({ behavior: "smooth", block: "start" });
		});
	};
	const settingByKey = useMemo(() => {
		const map = new Map<string, AdminSettingDef>();
		for (const section of settingSections) {
			for (const setting of section.settings) map.set(setting.key, setting);
		}
		return map;
	}, [settingSections]);


	const handleInlineSave = useCallback(async () => {
		if (!editingKey) return;
		setSaving(true);
		try {
			await admin.updateSetting(editingKey, { value: editingValue });
			toast.success(`Saved ${editingKey}`);
			if (editingKey === "misc.harness_allowlist" || editingKey === "misc.default_harness") {
				queryClient.invalidateQueries({ queryKey: ["config", "harnesses"] });
			}
			setEditingKey(null);
			setEditingValue("");
			refetch();
			refetchRestartStatus();
		} catch (e) {
			toast.error(e instanceof Error ? e.message : "Failed to save");
		} finally {
			setSaving(false);
		}
	}, [editingKey, editingValue, queryClient, refetch, refetchRestartStatus]);

	const renderSettingEditor = (key: string) => {
		if (key === "misc.harness_allowlist") {
			return <HarnessAllowlistEditor value={editingValue} onChange={setEditingValue} harnesses={harnesses} />;
		}
		if (key === "misc.default_harness") {
			return (
				<PickerSelect
					value={editingValue || "__none__"}
					onValueChange={(value) => setEditingValue(value === "__none__" ? "" : value)}
					placeholder="Choose default harness"
					className="flex-1"
					inputClassName="h-8 text-sm"
					options={[
						{ value: "__none__", label: "Use first allowed harness" },
						...harnesses.map((harness) => ({ value: harness.name, label: harness.display_name })),
					]}
				/>
			);
		}
		return (
			<Input
				value={editingValue}
				onChange={(e) => setEditingValue(e.target.value)}
				placeholder={settingByKey.get(key)?.default || "Enter value..."}
				className="h-8 text-sm flex-1 font-[family-name:var(--font-mono)]"
				autoFocus
				onKeyDown={(e) => {
					if (e.key === "Enter") handleInlineSave();
					if (e.key === "Escape") {
						setEditingKey(null);
						setEditingValue("");
					}
				}}
			/>
		);
	};

	const handleApplyResources = useCallback(async () => {
		setApplyingResources(true);
		try {
			const res = await admin.applyResources();
			const count = Object.keys(res.applied).length;
			if (count > 0) {
				toast.success(
					`Applied ${count} resource setting${count > 1 ? "s" : ""} to ClickHouse`,
				);
			} else {
				toast.info(
					"No resource settings configured yet. Add resource.* settings first.",
				);
			}
		} catch (e) {
			toast.error(
				e instanceof Error ? e.message : "Failed to apply resource settings",
			);
		} finally {
			setApplyingResources(false);
		}
	}, []);


	if (!ready) return null;

	return (
		<>
			<PageHeader
				title="Settings"
				breadcrumbs={[
					{ label: "Dashboard", href: "/dashboard" },
					{ label: "Settings" },
				]}
				actionButtonsRight={restartStatus?.required ? (
					<Button size="sm" variant="outline" onClick={restartApi} disabled={restarting}>
						{restarting ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Power className="mr-1.5 h-3.5 w-3.5" />}
						{restarting ? "Restarting" : "Restart API"}
					</Button>
				) : null}
			/>
			<div id="settings-page" className="page-body mx-auto w-full max-w-5xl space-y-8 pb-20">
				<div className="flex flex-col gap-6 border-b border-border pb-7 md:flex-row md:items-end md:justify-between">
					<div className="min-w-0">
						{activeCategory !== "home" && <button type="button" onClick={() => goToCategory("home")} className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-ring"><ArrowLeft className="size-4" /> All settings</button>}
						<h2 className="text-3xl font-semibold tracking-tight">{activeCategory === "home" ? "Settings" : CATEGORIES.find((category) => category.id === activeCategory)?.label}</h2>
						<p className="mt-2 max-w-xl text-sm text-muted-foreground">{activeCategory === "home" ? "Manage your instance by task. Choose an area below or find a specific setting." : CATEGORIES.find((category) => category.id === activeCategory)?.description}</p>
					</div>
					<div className="relative w-full shrink-0 md:w-72">
						<label htmlFor="settings-search" className="sr-only">Find a setting</label>
						<Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
						<Input id="settings-search" name="observal-settings-filter" type="search" value={navQuery}
							readOnly={!searchFocused} onFocus={() => setSearchFocused(true)} onBlur={() => setSearchFocused(false)}
							onChange={(event) => setNavQuery(event.target.value)}
							onKeyDown={(event) => { if (event.key === "Escape") setNavQuery(""); if (event.key === "Enter" && searchResults[0]) goToSection(searchResults[0].id); }}
							placeholder="Find a setting..." autoComplete="off" className="bg-card pl-9" />
						{navQuery.trim() && (
							<div className="absolute inset-x-0 top-full z-40 mt-1 max-h-72 overflow-auto rounded-lg border border-border bg-popover p-1 shadow-md" role="region" aria-label="Matching settings">
								{searchResults.length ? searchResults.map((result) => (
									<button key={result.id} type="button" onClick={() => goToSection(result.id)} className="flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring">
										<span>{result.label}</span><span className="text-xs text-muted-foreground">{CATEGORIES.find((category) => category.id === categoryForSection(result.id))?.label}</span>
									</button>
								)) : <p className="px-3 py-2 text-sm text-muted-foreground">No matching settings</p>}
							</div>
						)}
					</div>
				</div>
				{activeCategory === "home" ? (
					<div className="grid gap-x-10 gap-y-9 lg:grid-cols-2">
						{CATEGORIES.map((category) => {
							const Icon = category.icon;
							const sections = searchableSections.filter((section) => categoryForSection(section.id) === category.id);
							return (
							<section key={category.id} className="min-w-0 overflow-hidden rounded-lg border border-border bg-card">
								<button type="button" onClick={() => goToCategory(category.id)} className="group flex w-full items-start gap-3 border-b border-border p-4 text-left focus-visible:rounded-sm focus-visible:outline-2 focus-visible:outline-ring">
									<span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md bg-muted text-foreground"><Icon className="size-4" /></span>
									<span className="min-w-0 flex-1"><span className="block text-base font-semibold group-hover:underline group-hover:underline-offset-4">{category.label}</span><span className="mt-1 block text-xs leading-5 text-muted-foreground">{category.description}</span></span>
									<ArrowUpRight className="mt-1 size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-foreground" />
								</button>
								<div className="grid grid-cols-2 gap-x-4 gap-y-1 px-4 py-3">
									{sections.map((section) => <button key={section.id} type="button" onClick={() => goToSection(section.id)} className="min-w-0 rounded-sm py-1.5 text-left text-sm text-muted-foreground hover:text-foreground hover:underline hover:underline-offset-4 focus-visible:outline-2 focus-visible:outline-ring">{section.label}</button>)}
								</div>
							</section>
							);
						})}
					</div>
				) : (
					<nav aria-label="Sections in this area" className="flex flex-wrap gap-2">
						{searchableSections.filter((section) => categoryForSection(section.id) === activeCategory).map((section) => (
							<button key={section.id} type="button" onClick={() => goToSection(section.id)} className="rounded-md border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground hover:border-foreground/40 hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring">{section.label}</button>
						))}
					</nav>
				)}
				{activeCategory === "home" && getUserRole() === "super_admin" && <Link to="/review-policy" className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-3 text-sm font-medium hover:bg-muted/50 focus-visible:outline-2 focus-visible:outline-ring"><span className="flex items-center gap-2"><Shield className="size-4" /> Review policy</span><span className="text-xs font-normal text-muted-foreground">Approval counts and publication rules →</span></Link>}
				{restartStatus?.required && <p role="status" className="rounded-lg border border-border bg-card px-4 py-3 text-sm">Saved changes require an API restart to take effect.</p>}
				{/* Security warnings */}
				{systemWarnings && systemWarnings.length > 0 && (
					<section aria-label="Deployment notices" className="divide-y divide-border rounded-lg border border-border bg-card">
						{systemWarnings.map((w: SystemWarning) => (
							<div key={w.code} role={w.level === "critical" ? "alert" : "status"} className="flex items-start gap-3 px-4 py-3">
								{w.level === "critical" ? <ShieldAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-destructive" /> : <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warning" />}
								<p className="text-sm leading-5"><strong className="mr-2 font-semibold">{w.level === "critical" ? "Action required" : "Deployment notice"}</strong><span className="text-muted-foreground">{w.message}</span></p>
							</div>
						))}
					</section>
				)}
				<div className={activeCategory === "general" ? "space-y-8" : "hidden"}>
				{/* Appearance */}
				<section id="settings-appearance" data-settings-section className="scroll-mt-6 overflow-hidden rounded-lg border border-border bg-card">
					<h2 className={`flex items-center gap-2 border-b border-border px-5 py-4 text-lg font-medium tracking-tight ${sectionHelpHeadingClass("Appearance")}`} onClick={(event) => { if ((event.ctrlKey || event.metaKey) && openHelp(undefined, "Appearance")) event.preventDefault(); }}>
						<Palette className="h-3.5 w-3.5" />
						Appearance
						<button type="button" className="text-muted-foreground hover:text-primary" onClick={(event) => { event.preventDefault(); event.stopPropagation(); openHelp(undefined, "Appearance"); }} aria-label="Open Appearance documentation">
							<HelpCircle className="h-3.5 w-3.5" />
						</button>
					</h2>
					<div>
						<div className="grid lg:grid-cols-[minmax(200px,0.8fr)_minmax(0,1.2fr)]">
							<div className="flex flex-col justify-between gap-4 border-b border-border bg-muted/30 p-4 lg:border-b-0 lg:border-r lg:p-6">
								<div>
									<p className="mb-4 text-xs font-medium text-muted-foreground">Navigation preview</p>
									<div className="inline-flex items-center gap-3 rounded-lg border border-border bg-sidebar px-4 py-3">
										<img src={logoPreview || "/observal-logo.svg"} alt="" width={28} height={28} className="size-7 object-contain" />
										{wordmarkPreview ? (
											<img src={wordmarkPreview} alt={appNameDraft.trim() || "Observal"} className="h-5 max-w-40 object-contain" />
										) : (
											<span className="font-display text-base font-semibold text-sidebar-foreground">{appNameDraft.trim() || "Observal"}</span>
										)}
									</div>
								</div>
								<p className="max-w-xs text-xs leading-5 text-muted-foreground">PNG, SVG, ICO, JPEG, or WEBP. Max 2MB. Transparent images recommended for theme compatibility.</p>
							</div>
							<div className="grid gap-5 p-5 sm:grid-cols-2">
							{/* Logo icon */}
							<div className="space-y-2">
								<p className="text-xs font-medium">Icon</p>
								<div className="flex items-center gap-3">
								<div
									className="w-12 h-12 rounded border-2 border-dashed border-border flex items-center justify-center cursor-pointer hover:border-primary/50 transition-colors bg-muted/30"
									onClick={() => fileInputRef.current?.click()}
									onDragOver={(e) => e.preventDefault()}
									onDrop={(e) => {
										e.preventDefault();
										const f = e.dataTransfer.files[0];
										if (f) handleImageFile(f, setLogoOverride);
									}}
								>
									{logoPreview ? (
										<img
											src={logoPreview}
											alt="Icon"
											width={32}
											height={32}
											className="object-contain"
										/>
									) : (
										<Upload className="h-4 w-4 text-muted-foreground" />
									)}
								</div>
								<input
									ref={fileInputRef}
									type="file"
									accept="image/png,image/svg+xml,image/x-icon,image/jpeg,image/webp"
									className="hidden"
									onChange={(e) => {
										const f = e.target.files?.[0];
										if (f) handleImageFile(f, setLogoOverride);
										e.target.value = "";
									}}
								/>
								<div className="flex flex-wrap gap-1">
									<Button
										variant="outline"
										size="sm"
										className="h-9"
										onClick={() => fileInputRef.current?.click()}
									>
										Upload icon
									</Button>
									{logoPreview && (
										<Button
											variant="ghost"
											size="sm"
											className="h-9 text-muted-foreground"
											onClick={() => setLogoOverride(null)}
										>
											Remove
										</Button>
									)}
								</div>
								</div>
							</div>
							{/* Wordmark */}
							<div className="space-y-1.5">
								<p className="text-xs font-medium">
									Wordmark{" "}
									<span className="text-muted-foreground font-normal">
										(optional, replaces text)
									</span>
								</p>
								<div className="flex items-center gap-3">
								<div
									className="w-28 h-12 rounded border-2 border-dashed border-border flex items-center justify-center cursor-pointer hover:border-primary/50 transition-colors bg-muted/30"
									onClick={() => wordmarkInputRef.current?.click()}
									onDragOver={(e) => e.preventDefault()}
									onDrop={(e) => {
										e.preventDefault();
										const f = e.dataTransfer.files[0];
										if (f) handleImageFile(f, setWordmarkOverride);
									}}
								>
									{wordmarkPreview ? (
										<img
											src={wordmarkPreview}
											alt="Wordmark"
											width={96}
											height={24}
											className="h-6 max-w-24 object-contain"
										/>
									) : (
										<Upload className="h-4 w-4 text-muted-foreground" />
									)}
								</div>
								<input
									ref={wordmarkInputRef}
									type="file"
									accept="image/png,image/svg+xml,image/x-icon,image/jpeg,image/webp"
									className="hidden"
									onChange={(e) => {
										const f = e.target.files?.[0];
										if (f) handleImageFile(f, setWordmarkOverride);
										e.target.value = "";
									}}
								/>
								<div className="flex flex-wrap gap-1">
									<Button
										variant="outline"
										size="sm"
										className="h-9"
										onClick={() => wordmarkInputRef.current?.click()}
									>
										Upload wordmark
									</Button>
									{wordmarkPreview && (
										<Button
											variant="ghost"
											size="sm"
											className="h-9 text-muted-foreground"
											onClick={() => setWordmarkOverride(null)}
										>
											Remove
										</Button>
									)}
								</div>
								</div>
							</div>
							{/* App name (text fallback) */}
							<div className="space-y-1.5 sm:col-span-2">
								<label htmlFor="branding-app-name" className="block text-xs font-medium">
									App Name{" "}
									<span className="text-muted-foreground font-normal">
										(used when no wordmark)
									</span>
								</label>
								<Input
									id="branding-app-name"
									value={appNameDraft}
									onChange={(e) => setAppNameOverride(e.target.value)}
									placeholder="Observal"
									autoComplete="off"
									maxLength={30}
									className="h-9 w-full max-w-sm text-sm"
								/>
								<p className="text-[11px] text-muted-foreground">
									{appNameDraft.length}/30
								</p>
							</div>
						</div>
						</div>
						<div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
							<div className="flex items-center gap-2">
								<Button
									size="sm"
									className="h-9"
									onClick={handleSaveBranding}
									disabled={brandingSaving || !hasBrandingChanges}
								>
									{brandingSaving ? (
										<Loader2 className="mr-1 h-3 w-3 animate-spin" />
									) : (
										<Save className="mr-1 h-3 w-3" />
									)}
									Save
								</Button>
								{(brandingLogo || brandingAppName || brandingWordmark) && (
									<Button
										size="sm"
										variant="outline"
										className="h-9"
										onClick={handleResetBranding}
										disabled={brandingSaving}
									>
										<RotateCcw className="mr-1 h-3 w-3" />
										Reset
									</Button>
								)}
							</div>
						</div>
					</div>
				</section>

				{/* Experimental features */}
				<section id="settings-experimental" data-settings-section className="scroll-mt-6 overflow-hidden rounded-lg border border-border bg-card">
					<div className="border-b border-border px-5 py-4">
						<h2 className="flex items-center gap-2 text-lg font-medium tracking-tight"><FlaskConical className="size-4" />Experimental</h2>
						<p className="mt-1 text-xs text-muted-foreground">Features that are not ready for general use. Off by default, and hidden everywhere while off.</p>
					</div>
					<div className="flex items-center justify-between gap-4 px-5 py-4">
						<div className="flex-1">
							<p className="text-sm font-medium">Review checks</p>
							<p className="mt-0.5 text-xs text-muted-foreground">Automated checks on review revisions, with per-organization and per-teamspace settings. Behavior and APIs may change or be removed.</p>
						</div>
						<Switch checked={experimentalReviewChecks} onCheckedChange={handleReviewChecksToggle} disabled={reviewChecksToggling} aria-label="Enable experimental review checks" />
					</div>
				</section>

				<div id="settings-access" data-settings-section className="scroll-mt-6 overflow-hidden rounded-lg border border-border bg-card">
				<div className="border-b border-border px-5 py-4"><h2 className="text-lg font-medium tracking-tight">Access & privacy</h2>
				<p className="mt-1 text-xs text-muted-foreground">Control public access and trace visibility.</p></div>
				<div className="divide-y divide-border">
				{/* Public registry access */}
				<section className="px-5 py-4">
										<div>
						<div className="flex items-center justify-between gap-4">
							<div className="flex-1">
								<p className="text-sm font-medium">Allow public browsing and installs</p>
								<p className="text-xs text-muted-foreground mt-0.5">
									Signed-out visitors can browse and install approved public Agent Files and components. Publishing, private content, telemetry, and administration still require sign-in.
								</p>
							</div>
							<Switch
								checked={publicRegistryEnabled}
								onCheckedChange={handlePublicRegistryToggle}
								disabled={publicRegistryToggling}
								aria-label="Allow public registry browsing and installs"
							/>
						</div>
					</div>
				</section>

				{/* Trace Privacy */}
				<section className="px-5 py-4">
					<h3 className={`mb-2 flex items-center gap-2 text-sm font-medium ${sectionHelpHeadingClass("Trace Privacy")}`} onClick={(event) => { if ((event.ctrlKey || event.metaKey) && openHelp(undefined, "Trace Privacy")) event.preventDefault(); }}>
						<Eye className="h-3.5 w-3.5" />
						Restrict trace visibility
						<button type="button" className="text-muted-foreground hover:text-primary" onClick={(event) => { event.preventDefault(); event.stopPropagation(); openHelp(undefined, "Trace Privacy"); }} aria-label="Open Trace Privacy documentation">
							<HelpCircle className="h-3.5 w-3.5" />
						</button>
					</h3>
					<div>
						<div className="flex items-center justify-between">
							<div className="flex-1">
								<p className="text-xs text-muted-foreground mt-0.5">
									When enabled, all users (including admins) can only see their
									own traces. Super-admins always retain full visibility across
									all traces.
								</p>
							</div>
							<Switch
								checked={tracePrivacy}
								onCheckedChange={handleTracePrivacyToggle}
								disabled={tracePrivacyLoading || tracePrivacyToggling}
							/>
						</div>
					</div>
				</section>

				{/* Interface: Leaderboard tab visibility */}
				<section className="px-5 py-4">
					<h3 className="mb-2 flex items-center gap-1.5 text-sm font-medium">
						<PanelLeft className="h-3.5 w-3.5" />
						Interface
					</h3>
					<div>
						<div className="flex items-center justify-between gap-4">
							<div className="flex-1">
								<p className="text-sm font-medium">Show the Leaderboard</p>
								<p className="text-xs text-muted-foreground mt-0.5">
									Off by default. When off, the Leaderboard tab, its home page link,
									the page, and its API are unavailable to everyone, including admins.
									Ranking data is kept. {LEADERBOARD_DEPRECATION_NOTICE}
								</p>
							</div>
							<Switch
								checked={leaderboardEnabled}
								onCheckedChange={(checked) => {
									if (checked) setShowLeaderboardConfirm(true);
									else void handleLeaderboardToggle(false);
								}}
								disabled={leaderboardToggling}
								aria-label="Show the Leaderboard"
							/>
						</div>
					</div>
					<Dialog open={showLeaderboardConfirm} onOpenChange={setShowLeaderboardConfirm}>
						<DialogContent className="max-w-md">
							<DialogHeader>
								<DialogTitle className="flex items-center gap-2 text-sm">
									<AlertTriangle className="h-4 w-4 text-warning" />
									Turn on the Leaderboard?
								</DialogTitle>
								<DialogDescription className="text-xs">
									{LEADERBOARD_DEPRECATION_NOTICE} Everyone will see the Leaderboard tab
									and page until you turn it off again.
								</DialogDescription>
							</DialogHeader>
							<DialogFooter>
								<Button size="sm" variant="outline" onClick={() => setShowLeaderboardConfirm(false)}>
									Cancel
								</Button>
								<Button
									size="sm"
									onClick={() => {
										setShowLeaderboardConfirm(false);
										void handleLeaderboardToggle(true);
									}}
								>
									Turn on
								</Button>
							</DialogFooter>
						</DialogContent>
					</Dialog>
				</section>

				{/* Registered Agents Only, super_admin only */}
				{hasMinRole(getUserRole(), "super_admin") && (
					<section className="px-5 py-4">
						<h3 className={`mb-2 flex items-center gap-2 text-sm font-medium ${sectionHelpHeadingClass("Registered Agent Files Only")}`} onClick={(event) => { if ((event.ctrlKey || event.metaKey) && openHelp(undefined, "Registered Agent Files Only")) event.preventDefault(); }}>
							<Shield className="h-3.5 w-3.5" />
							Only trace registered Agent Files
							<button type="button" className="text-muted-foreground hover:text-primary" onClick={(event) => { event.preventDefault(); event.stopPropagation(); openHelp(undefined, "Registered Agent Files Only"); }} aria-label="Open Registered Agent Files Only documentation">
								<HelpCircle className="h-3.5 w-3.5" />
							</button>
						</h3>
						<div>
							<div className="flex items-center justify-between">
								<div className="flex-1">

									<p className="text-xs text-muted-foreground mt-0.5">
										Unstable. When enabled, only registered Agent Files are traced.
										Unregistered Agent File activity may be missing from traces.
									</p>
								</div>
								<Switch
									checked={registeredAgentsOnly}
									onCheckedChange={handleRegisteredAgentsOnlyToggle}
									disabled={
										registeredAgentsOnlyLoading || registeredAgentsOnlyToggling
									}
								/>
							</div>
						</div>
					</section>
				)}
				<div className="flex flex-wrap gap-x-8 gap-y-2 px-5 py-4 text-xs text-muted-foreground">
					<span>SSO (OAuth/OIDC): <strong className="font-medium text-foreground">{ssoEnabled ? "Enabled" : "Disabled"}</strong></span>
					<span>SAML SSO: <strong className="font-medium text-foreground">{samlEnabled ? "Configured" : "Not configured"}</strong></span>
				</div>
				</div>
				</div>
				<div id="settings-usage" data-settings-section className="scroll-mt-6 overflow-hidden rounded-lg border border-border bg-card"><UsagePingSection settings={entries} onChanged={() => { void refetch(); }} /></div>
				</div>
				<div className={activeCategory === "insights" ? "" : "hidden"}>
				{settingSections.some((section) => section.id === "insights" && section.settings.length > 0) && (
					<div id="settings-insights" data-settings-section className="scroll-mt-6 overflow-hidden rounded-lg border border-border bg-card">
						<InsightsSection
							entries={entries}
							onSave={async (key, value) => { await admin.updateSetting(key, { value }); refetch(); }}
							onRevoke={(key) => setRevokeConfirmKey(key)}
							refetch={refetch}
						/>
					</div>
				)}
				</div>
				<div className={activeCategory === "data" ? "space-y-8" : "hidden"}>
				{/* Data Migration, super_admin only */}
				{hasMinRole(getUserRole(), "super_admin") && (
					<section id="settings-migration" data-settings-section className="scroll-mt-6 overflow-hidden rounded-lg border border-border bg-card">
						<h3 className={`flex items-center gap-2 border-b border-border px-5 py-4 text-lg font-medium tracking-tight ${sectionHelpHeadingClass("Data Migration")}`} onClick={(event) => { if ((event.ctrlKey || event.metaKey) && openHelp(undefined, "Data Migration")) event.preventDefault(); }}>
							<ArrowLeftRight className="h-3.5 w-3.5" />
							Data Migration
							<button type="button" className="text-muted-foreground hover:text-primary" onClick={(event) => { event.preventDefault(); event.stopPropagation(); openHelp(undefined, "Data Migration"); }} aria-label="Open Data Migration documentation">
								<HelpCircle className="h-3.5 w-3.5" />
							</button>
						</h3>
						<div className="px-5 py-4">
							<div className="flex items-center justify-between gap-4">
								<div className="flex-1">
									<p className="text-sm font-medium">
										Export, import, and validate instance data
									</p>
									<p className="text-xs text-muted-foreground mt-0.5">
										Move registry data and telemetry between Observal instances. Start with the guide if this is your first run.
									</p>
								</div>
								<div className="flex items-center gap-2">
									<Button type="button" variant="outline" size="sm" onClick={() => openHelpCtx({ pageKey: "migration" })}>
										<HelpCircle className="h-3.5 w-3.5" />
										Guide
									</Button>
									<Button type="button" size="sm" onClick={() => setMigrateOpen(true)}>
										<ArrowLeftRight className="h-3.5 w-3.5" />
										Migrate
									</Button>
								</div>
							</div>
						</div>
						<MigrateDialog open={migrateOpen} onOpenChange={setMigrateOpen} />
					</section>
				)}

				{/* Data Retention, super_admin only */}
				{hasMinRole(getUserRole(), "super_admin") && (
					<section id="settings-retention" data-settings-section className="scroll-mt-6 overflow-hidden rounded-lg border border-border bg-card">
						<h3 className={`flex items-center gap-2 border-b border-border px-5 py-4 text-lg font-medium tracking-tight ${sectionHelpHeadingClass("Data Retention")}`} onClick={(event) => { if ((event.ctrlKey || event.metaKey) && openHelp(undefined, "Data Retention")) event.preventDefault(); }}>
							<Database className="h-3.5 w-3.5" />
							Data Retention
							<button type="button" className="text-muted-foreground hover:text-primary" onClick={(event) => { event.preventDefault(); event.stopPropagation(); openHelp(undefined, "Data Retention"); }} aria-label="Open Data Retention documentation">
								<HelpCircle className="h-3.5 w-3.5" />
							</button>
						</h3>
						<div className="space-y-4 p-5">
							<div className="flex items-center justify-between">
								<div className="flex-1">
									<p className="text-sm font-medium">Enable data retention</p>
									<p className="text-xs text-muted-foreground mt-0.5">
										Automatically purge telemetry data older than the configured
										period. Global ceiling:{" "}
										{retentionGlobal > 0
											? `${retentionGlobal} days`
											: "disabled"}
										.
									</p>
								</div>
								<Switch
									checked={retentionEnabled}
									onCheckedChange={setRetentionEnabled}
									disabled={retentionLoading}
								/>
							</div>

							{retentionEnabled && (
								<div className="space-y-3 pt-2 border-t border-border/50">
									<div>
										<label className="text-xs text-muted-foreground">
											Trace retention (days)
										</label>
										<Input
											type="number"
											min={7}
											max={retentionGlobal > 0 ? retentionGlobal : undefined}
											value={retentionDays}
											onChange={(e) => setRetentionDays(e.target.value)}
											placeholder="e.g. 30"
											className="h-8 text-sm mt-1 max-w-[200px]"
										/>
										{retentionErrors.data_retention_days && (
											<p className="text-xs text-destructive mt-1">
												{retentionErrors.data_retention_days}
											</p>
										)}
									</div>
									<div>
										<label className="text-xs text-muted-foreground">
											Score & insight retention (days)
										</label>
										<Input
											type="number"
											min={7}
											value={scoreRetentionDays}
											onChange={(e) => setScoreRetentionDays(e.target.value)}
											placeholder="e.g. 30 (default: 2x trace retention)"
											className="h-8 text-sm mt-1 max-w-[200px]"
										/>
										{retentionErrors.score_retention_days && (
											<p className="text-xs text-destructive mt-1">
												{retentionErrors.score_retention_days}
											</p>
										)}
									</div>
									<div>
										<label className="text-xs text-muted-foreground">
											Max trace count (optional)
										</label>
										<Input
											type="number"
											min={1000}
											value={maxTraceCount}
											onChange={(e) => setMaxTraceCount(e.target.value)}
											placeholder="e.g. 100000"
											className="h-8 text-sm mt-1 max-w-[200px]"
										/>
										{retentionErrors.max_trace_count && (
											<p className="text-xs text-destructive mt-1">
												{retentionErrors.max_trace_count}
											</p>
										)}
									</div>
									{retentionErrors.general && (
										<p className="text-xs text-destructive">
											{retentionErrors.general}
										</p>
									)}
								</div>
							)}

							<div className="flex justify-end pt-2">
								<Button
									size="sm"
									className="h-8"
									onClick={handleRetentionSave}
									disabled={
										retentionLoading || retentionSaving || hasRetentionErrors
									}
								>
									{retentionSaving ? (
										<Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
									) : (
										<Save className="h-3.5 w-3.5 mr-1.5" />
									)}
									Save
								</Button>
							</div>
						</div>

						{/* Confirmation dialog */}
						<Dialog
							open={showRetentionConfirm}
							onOpenChange={(open) => {
								if (!open) {
									setShowRetentionConfirm(false);
									setRetentionPreview(null);
								}
							}}
						>
							<DialogContent className="max-w-md">
								<DialogHeader>
									<DialogTitle className="flex items-center gap-2 text-sm">
										<AlertTriangle className="h-4 w-4 text-amber-500" />
										Enable Data Retention?
									</DialogTitle>
									<DialogDescription className="text-xs">
										This will permanently delete telemetry data older than{" "}
										{retentionDays} days. Purges run automatically every 6
										hours. This action cannot be undone.
									</DialogDescription>
								</DialogHeader>
								{retentionPreview && (
									<div className="rounded bg-muted/50 p-3 text-xs space-y-1">
										<p className="font-medium text-muted-foreground">
											Estimated deletions:
										</p>
										{Object.entries(retentionPreview)
											.filter(([k]) => !k.startsWith("_"))
											.map(([k, v]) => (
												<p key={k}>
													{k}: {typeof v === "number" ? v.toLocaleString() : v}{" "}
													rows
												</p>
											))}
									</div>
								)}
								<label className="flex items-center gap-2 text-xs cursor-pointer">
									<Checkbox
										checked={retentionConfirmChecked}
										onCheckedChange={(checked) =>
											setRetentionConfirmChecked(checked === true)
										}
									/>
									I understand this will permanently delete data
								</label>
								<DialogFooter>
									<Button
										size="sm"
										variant="outline"
										onClick={() => {
											setShowRetentionConfirm(false);
											setRetentionPreview(null);
										}}
									>
										Cancel
									</Button>
									<Button
										size="sm"
										variant="destructive"
										onClick={handleRetentionConfirm}
										disabled={!retentionConfirmChecked}
									>
										Enable Retention
									</Button>
								</DialogFooter>
							</DialogContent>
						</Dialog>
					</section>
				)}
				</div>

				{isLoading ? (
					["data", "platform", "security"].includes(activeCategory) ? <TableSkeleton rows={5} cols={2} /> : null
				) : isError ? (
					<ErrorState message={error?.message} onRetry={() => refetch()} />
				) : (
					<div className="animate-in space-y-6">
						{settingSections.filter((s) => !s.danger && s.id !== "insights").sort((a, b) => {
							const order = ["data", "resource", "discovery", "registry", "jwt", "observability", "misc"];
							return order.indexOf(a.id) - order.indexOf(b.id);
						}).map((section) => {
								const visibleSettings = section.settings.filter(
									(setting) => !DEDICATED_TOGGLE_KEYS.has(setting.key),
								);
								if (visibleSettings.length === 0) return null;

								return (
								<section key={section.title} id={`settings-${section.id}`} data-settings-section className={activeCategory === categoryForSection(section.id) ? "scroll-mt-6 overflow-hidden rounded-lg border border-border bg-card" : "hidden"}>
									<h3
										className={`flex items-center gap-2 px-5 pt-4 text-lg font-medium tracking-tight ${helpActive && SECTION_DOCS[section.title] ? "cursor-help ring-2 ring-primary/60 ring-offset-2 ring-offset-background rounded-sm" : ""}`}
										onClick={(event) => {
											if ((event.ctrlKey || event.metaKey) && openHelp(undefined, section.title)) {
												event.preventDefault();
											}
										}}
									>
										{sectionIcon(section)}
										{section.title}
										{SECTION_DOCS[section.title] && (
											<button type="button" className="ml-1 text-muted-foreground hover:text-primary" onClick={(event) => { event.preventDefault(); event.stopPropagation(); openHelp(undefined, section.title); }} aria-label={`Open ${section.title} documentation`}>
												<HelpCircle className="h-3.5 w-3.5" />
											</button>
										)}
									</h3>
									{section.description && (
										<p className="px-5 pb-4 pt-1 text-xs text-muted-foreground">{section.description}</p>
									)}
									<div className="divide-y divide-border border-t border-border">
									{visibleSettings.map((d) => {
										const existing = entries.find((e) => e.key === d.key);
										const isEditing = editingKey === d.key;
										const isBool = d.default === "true" || d.default === "false";
										if (isBool && !isEditing) {
											return <BoolSettingCard key={d.key} def={d} value={(existing?.value || d.default) === "true"} helpClass={helpTargetClass(d.key)} openHelp={openHelp} onToggle={async (checked) => { try { await admin.updateSetting(d.key, { value: checked ? "true" : "false" }); await queryClient.invalidateQueries({ queryKey: ["config", "public"] }); await refetch(); refetchRestartStatus(); toast.success(`${d.label} ${checked ? "enabled" : "disabled"}`); } catch (e) { toast.error(e instanceof Error ? e.message : `Failed to update ${d.label}`); } }} />;
										}
										if (isEditing) {
											return (
												<div key={d.key} className={`grid gap-3 bg-primary/5 px-5 py-4 md:grid-cols-[minmax(0,1fr)_minmax(220px,1fr)] md:items-center ${helpTargetClass(d.key)}`} onClick={(e) => { if ((e.ctrlKey || e.metaKey) && openHelp(d.key)) { e.preventDefault(); e.stopPropagation(); } }}>
													<div className="mb-2 flex items-center gap-2"><span className="text-sm font-semibold text-foreground">{d.label}</span>{d.restart_required && <RestartRequiredMark />}</div>
													<div className="flex items-center gap-2">
														{renderSettingEditor(d.key)}
														<Button size="sm" className="h-9 gap-1.5" onClick={handleInlineSave} disabled={saving}>{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />} Save</Button>
														<Button size="sm" variant="ghost" className="h-9" onClick={() => { setEditingKey(null); setEditingValue(""); }}>Cancel</Button>
													</div>
												</div>
											);
										}
										if (existing && existing.value) {
											const isSensitive = (existing as AdminSetting).is_sensitive || SENSITIVE_KEYS.has(d.key);
											const isSet = (existing as AdminSetting).is_set ?? !!existing.value;
											return (
												<div key={d.key} className={`relative grid gap-2 px-5 py-4 md:grid-cols-[minmax(0,1fr)_minmax(220px,1fr)] md:items-center ${helpTargetClass(d.key)}`}  onClick={(e) => { if ((e.ctrlKey || e.metaKey) && openHelp(d.key)) { e.preventDefault(); e.stopPropagation(); } }}>
													<SettingHelpIcon settingKey={d.key} openHelp={openHelp} />
													<div className="pr-6"><div className="flex items-center gap-2"><span className="text-sm font-medium text-foreground">{d.label}</span>{d.restart_required && <RestartRequiredMark />}</div>{d.subtitle && <p className="mt-1 text-xs text-muted-foreground">{d.subtitle}</p>}</div>
													<div className="flex min-w-0 items-center gap-2">
														{isSensitive ? (
															<span className="text-xs text-foreground/70 font-[family-name:var(--font-mono)] truncate flex-1">{isSet ? REDACTED_VALUE : "Not set"}</span>
														) : (
															<span className="text-xs text-foreground/70 font-[family-name:var(--font-mono)] truncate flex-1">{existing.value}</span>
														)}
														<Button variant="outline" size="sm" className="h-8" onClick={() => { setEditingKey(d.key); setEditingValue(isSensitive ? "" : (existing?.value ?? "")); }}>Edit</Button>
														{isSensitive && isSet ? (
															<Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => setRevokeConfirmKey(d.key)}><Trash2 className="h-3 w-3 text-muted-foreground hover:text-destructive" /></Button>
														) : (
															<Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={async () => { await admin.updateSetting(d.key, { value: "" }); refetch(); refetchRestartStatus(); toast.success(`Cleared ${d.label}`); }}><Trash2 className="h-3 w-3 text-muted-foreground hover:text-destructive" /></Button>
														)}
													</div>
												</div>
											);
										}
										return (
											<div key={d.key} className={`relative grid gap-2 py-4 pl-5 pr-12 md:grid-cols-[minmax(0,1fr)_minmax(220px,1fr)] md:items-center ${helpTargetClass(d.key)}`}>
												<SettingHelpIcon settingKey={d.key} openHelp={openHelp} />
												<div className="flex items-center gap-2 pr-6"><span className="text-sm font-medium">{d.label}</span>{d.restart_required && <RestartRequiredMark />}</div>
												<div className="flex items-center justify-between gap-3"><span className="text-xs text-muted-foreground">Not set</span><Button variant="outline" size="sm" className="h-8" onClick={() => { setEditingKey(d.key); setEditingValue(""); }}>Configure</Button></div>
											</div>
										);
									})}
									</div>
								</section>
								);
							})}

							{/* Danger Zone */}
							{settingSections.some((s) => s.danger) && (
								<section className={activeCategory === "security" ? "" : "hidden"}>
									<div className="space-y-4">
											{settingSections.filter((s) => s.danger).sort((a, b) => {
											const order = ["auth", "deployment", "security", "danger"];
											return order.indexOf(a.id) - order.indexOf(b.id);
										}).map((section) => {
												const visibleDangerSettings = section.settings.filter(
													(setting) => !DEDICATED_TOGGLE_KEYS.has(setting.key),
												);
												if (visibleDangerSettings.length === 0) return null;
												return (
												<details key={section.title} id={`settings-${section.id}`} data-settings-section open={section.id !== "danger"} className="group scroll-mt-6 rounded-xl border border-border bg-card">
													<summary className="flex items-center gap-2 px-4 py-3 cursor-pointer select-none hover:bg-muted/30 transition-colors">
														{sectionIcon(section)}
														<span className="text-sm font-semibold text-foreground/80 flex-1">{section.title}</span>
														{SECTION_DOCS[section.title] && (
															<button type="button" className="text-muted-foreground hover:text-primary" onClick={(e) => { e.preventDefault(); e.stopPropagation(); openHelp(undefined, section.title); }} aria-label={`Open ${section.title} documentation`}>
																<HelpCircle className="h-3.5 w-3.5" />
															</button>
														)}
														{section.id === "danger" && <span className="text-xs text-muted-foreground">Destructive</span>}
													</summary>
													<div className="border-t border-border">
														{section.description && (
															<p className="px-5 py-3 text-xs text-muted-foreground">{section.description}</p>
														)}
														<div className="divide-y divide-border border-t border-border">
															{visibleDangerSettings.map((d) => {
														if (d.key === "danger.purge_traces_insights") {
															return (
																<div key={d.key} className={`relative grid gap-3 px-5 py-4 md:grid-cols-[minmax(0,1fr)_minmax(220px,1fr)] md:items-center ${helpTargetClass(d.key)}`}>
																	<SettingHelpIcon settingKey={d.key} openHelp={openHelp} />
																	<div><span className="text-sm font-semibold text-foreground">{d.label}</span>
																	<p className="mt-1 text-xs text-muted-foreground">{d.subtitle}</p></div>
																	<Button variant="destructive" size="sm" className="h-8 justify-self-start md:justify-self-end" onClick={handlePurgeTracesInsights} disabled={purgingTracesInsights}>
																		{purgingTracesInsights ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Trash2 className="mr-1 h-3.5 w-3.5" />}
																		Purge traces & insights
																	</Button>
																</div>
															);
														}
														const existing = entries.find((e) => e.key === d.key);
														const isEditing = editingKey === d.key;
														const isBool = d.default === "true" || d.default === "false";
										if (isBool && !isEditing) {
											return <BoolSettingCard key={d.key} def={d} value={(existing?.value || d.default) === "true"} helpClass={helpTargetClass(d.key)} openHelp={openHelp} onToggle={async (checked) => { try { await admin.updateSetting(d.key, { value: checked ? "true" : "false" }); await queryClient.invalidateQueries({ queryKey: ["config", "public"] }); await refetch(); refetchRestartStatus(); toast.success(`${d.label} ${checked ? "enabled" : "disabled"}`); } catch (e) { toast.error(e instanceof Error ? e.message : `Failed to update ${d.label}`); } }} />;
										}
														if (isEditing) {
															return (
																<div key={d.key} className="grid gap-3 bg-primary/5 px-5 py-4 md:grid-cols-[minmax(0,1fr)_minmax(220px,1fr)] md:items-center">
																	<div className="mb-2 flex items-center gap-2"><span className="text-sm font-semibold text-foreground">{d.label}</span>{d.restart_required && <RestartRequiredMark />}</div>
																	<div className="flex items-center gap-2">
																		{renderSettingEditor(d.key)}
																		<Button size="sm" className="h-8" onClick={handleInlineSave} disabled={saving}>{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}</Button>
																		<Button size="sm" variant="ghost" className="h-8" onClick={() => { setEditingKey(null); setEditingValue(""); }}><X className="h-3.5 w-3.5" /></Button>
																	</div>
																</div>
															);
														}
														if (existing && existing.value) {
															const isSensitive = (existing as AdminSetting).is_sensitive || SENSITIVE_KEYS.has(d.key);
															const isSet = (existing as AdminSetting).is_set ?? !!existing.value;
															return (
																<div key={d.key} className={`relative grid gap-2 px-5 py-4 md:grid-cols-[minmax(0,1fr)_minmax(220px,1fr)] md:items-center ${helpTargetClass(d.key)}`} onClick={(e) => { if ((e.ctrlKey || e.metaKey) && openHelp(d.key)) { e.preventDefault(); e.stopPropagation(); } }}>
																	<SettingHelpIcon settingKey={d.key} openHelp={openHelp} />
																	<div className="flex items-center gap-2 pr-6"><span className="text-sm font-semibold text-foreground">{d.label}</span>{d.restart_required && <RestartRequiredMark />}</div>
																	<div className="flex items-center gap-2 mt-1.5">
																		{isSensitive ? (
																			<span className="text-xs text-foreground/70 font-[family-name:var(--font-mono)] truncate flex-1">{isSet ? REDACTED_VALUE : "Not set"}</span>
																		) : (
																			<span className="text-xs text-foreground/70 font-[family-name:var(--font-mono)] truncate flex-1">{existing.value}</span>
																		)}
																		<Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => { setEditingKey(d.key); setEditingValue(isSensitive ? "" : existing.value); }}><Pencil className="h-3 w-3 text-muted-foreground" /></Button>
																		{isSensitive && isSet ? (
																			<Button variant="ghost" size="sm" className="h-8 text-destructive" onClick={() => setRevokeConfirmKey(d.key)}>Revoke</Button>
																		) : (
																			<Button variant="ghost" size="sm" className="h-8" onClick={async () => { await admin.updateSetting(d.key, { value: "" }); refetch(); refetchRestartStatus(); toast.success(`Cleared ${d.label}`); }}>Clear</Button>
																		)}
																	</div>
																</div>
															);
														}
														return (
															<div key={d.key} className={`relative flex flex-wrap items-center justify-between gap-3 py-4 pl-5 pr-12 ${helpTargetClass(d.key)}`}>
																<SettingHelpIcon settingKey={d.key} openHelp={openHelp} />
																<div className="flex items-center gap-2 pr-6"><span className="text-sm font-medium">{d.label}</span>{d.restart_required && <RestartRequiredMark />}</div>
																<Button variant="outline" size="sm" onClick={() => { setEditingKey(d.key); setEditingValue(""); }}>Configure</Button>
															</div>
														);
															})}
														</div>
													</div>
												</details>
											); })}
										</div>
								</section>
							)}
					</div>
				)}
			</div>
			<Dialog open={revokeConfirmKey !== null} onOpenChange={(open) => { if (!open) setRevokeConfirmKey(null); }}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>Revoke secret</DialogTitle>
						<DialogDescription>
							This will permanently delete the stored value for <strong>{revokeConfirmKey}</strong>. Any features depending on this credential will stop working immediately. This cannot be undone.
						</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<Button variant="outline" onClick={() => setRevokeConfirmKey(null)}>Cancel</Button>
						<Button variant="destructive" onClick={async () => { try { await admin.revokeSetting(revokeConfirmKey!); refetch(); refetchRestartStatus(); toast.success(`Revoked ${revokeConfirmKey}`); } catch (e: unknown) { toast.error(e instanceof Error ? e.message : "Failed to revoke setting"); } finally { setRevokeConfirmKey(null); } }}>Revoke</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</>
	);
}
