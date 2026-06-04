// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useState, useEffect, useCallback, useMemo } from "react";
import {
	Activity,
	Check,
	ChevronsUpDown,
	Eye,
	EyeOff,
	Loader2,
	Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
	Command,
	CommandEmpty,
	CommandGroup,
	CommandInput,
	CommandItem,
	CommandList,
} from "@/components/ui/command";
import {
	Popover,
	PopoverContent,
	PopoverTrigger,
} from "@/components/ui/popover";
import { admin } from "@/lib/api";
import { ModelCombobox } from "./model-combobox";
import {
	type ProviderId,
	type InsightsStatus,
	PROVIDERS,
	PROVIDER_MODELS,
	RECOMMENDED_MODELS,
	detectProvider,
	detectProviderFromKey,
	getInsightsStatus,
} from "./insights-constants";

interface InsightsSectionProps {
	entries: { key: string; value: string; is_sensitive?: boolean; is_set?: boolean }[];
	onSave: (key: string, value: string) => Promise<void>;
	onRevoke: (key: string) => void;
	refetch: () => void;
}

interface TestResult {
	success: boolean;
	model?: string;
	latency_ms?: number;
	error?: string;
	hint?: string;
}

export function InsightsSection({ entries, onSave, onRevoke, refetch }: InsightsSectionProps) {
	const getEntryValue = useCallback(
		(key: string) => {
			const entry = entries.find((e) => e.key === key);
			if (!entry) return "";
			if (entry.is_sensitive) return "";
			return entry.value || "";
		},
		[entries],
	);

	const isKeySet = useCallback(
		(key: string) => {
			const entry = entries.find((e) => e.key === key);
			return entry?.is_set || (entry?.value ? entry.value !== "" : false);
		},
		[entries],
	);

	// State
	const [provider, setProvider] = useState<ProviderId | "">("");
	const [providerOpen, setProviderOpen] = useState(false);
	const [apiKeyValue, setApiKeyValue] = useState("");
	const [showApiKey, setShowApiKey] = useState(false);
	const [apiBase, setApiBase] = useState("");
	const [modelSections, setModelSections] = useState("");
	const [modelSynthesis, setModelSynthesis] = useState("");
	const [modelFacets, setModelFacets] = useState("");
	const [batchEnabled, setBatchEnabled] = useState(true);
	const [batchPeriod, setBatchPeriod] = useState("14");
	const [minSessions, setMinSessions] = useState("5");
	const [maxFacetCalls, setMaxFacetCalls] = useState("100");
	const [facetConcurrency, setFacetConcurrency] = useState("25");
	const [saving, setSaving] = useState<Record<string, boolean>>({});
	const [testingConnection, setTestingConnection] = useState(false);
	const [testResult, setTestResult] = useState<TestResult | null>(null);

	// Initialize from entries
	useEffect(() => {
		const sections = getEntryValue("insights.model_sections");
		const synthesis = getEntryValue("insights.model_synthesis");
		const facets = getEntryValue("insights.model_facets");
		const base = getEntryValue("insights.api_base");
		const batch = getEntryValue("insights.batch_enabled");
		const period = getEntryValue("insights.batch_period_days");
		const sessions = getEntryValue("insights.min_sessions");
		const maxCalls = getEntryValue("insights.facet_max_calls");
		const concurrency = getEntryValue("insights.facet_concurrency");

		setModelSections(sections);
		setModelSynthesis(synthesis);
		setModelFacets(facets);
		setApiBase(base);
		setBatchEnabled(batch !== "false");
		setBatchPeriod(period || "14");
		setMinSessions(sessions || "5");
		setMaxFacetCalls(maxCalls || "100");
		setFacetConcurrency(concurrency || "25");

		const detected = detectProvider(sections);
		if (detected) setProvider(detected);
	}, [entries, getEntryValue]);

	// Auto-detect provider from API key
	useEffect(() => {
		if (apiKeyValue && !provider) {
			const detected = detectProviderFromKey(apiKeyValue);
			if (detected) setProvider(detected);
		}
	}, [apiKeyValue, provider]);

	// Derived values
	const status: InsightsStatus = useMemo(() => getInsightsStatus(entries), [entries]);
	const selectedProvider = useMemo(
		() => PROVIDERS.find((p) => p.id === provider),
		[provider],
	);
	const showBaseUrl = provider !== "";
	const suggestions = useMemo(
		() => (provider ? PROVIDER_MODELS[provider] || [] : []),
		[provider],
	);
	const showRecommended = useMemo(
		() =>
			provider !== "" &&
			RECOMMENDED_MODELS[provider] &&
			(!modelSections || !modelSynthesis || !modelFacets),
		[provider, modelSections, modelSynthesis, modelFacets],
	);

	// Handlers
	const handleSave = useCallback(
		async (key: string, value: string) => {
			setSaving((s) => ({ ...s, [key]: true }));
			try {
				await onSave(key, value);
			} catch {
				toast.error(`Failed to save ${key.split(".")[1]}`);
			} finally {
				setSaving((s) => ({ ...s, [key]: false }));
			}
		},
		[onSave],
	);

	const handleApiKeySave = useCallback(async () => {
		if (!apiKeyValue) return;
		await handleSave("insights.api_key", apiKeyValue);
		setApiKeyValue("");
	}, [apiKeyValue, handleSave]);

	const handleTestConnection = useCallback(async () => {
		setTestingConnection(true);
		setTestResult(null);
		try {
			const modelsToTest: { model: string; label: string }[] = [];
			if (modelSections) modelsToTest.push({ model: modelSections, label: "Sections" });
			if (modelSynthesis && modelSynthesis !== modelSections) modelsToTest.push({ model: modelSynthesis, label: "Synthesis" });
			if (modelFacets && modelFacets !== modelSections && modelFacets !== modelSynthesis) modelsToTest.push({ model: modelFacets, label: "Facets" });

			if (modelsToTest.length === 0) {
				setTestResult({
					success: false,
					error: "No models configured",
					hint: "Set at least the Sections Model before testing.",
				});
				return;
			}

			for (const { model, label } of modelsToTest) {
				const result = (await admin.testInsightsConnection({ model })) as TestResult;
				if (!result.success) {
					setTestResult({
						...result,
						error: `${label} Model failed: ${result.error}`,
					});
					return;
				}
			}

			setTestResult({
				success: true,
				model: modelsToTest.length === 1
					? modelsToTest[0].model
					: `All ${modelsToTest.length} models connected`,
				latency_ms: undefined,
			});
		} catch (e) {
			setTestResult({
				success: false,
				error: e instanceof Error ? e.message : "Request failed",
				hint: "Could not reach the server. Is it running?",
			});
		} finally {
			setTestingConnection(false);
		}
	}, [modelSections, modelSynthesis, modelFacets]);

	const handleUseRecommended = useCallback(async () => {
		if (!provider || !RECOMMENDED_MODELS[provider]) return;
		const rec = RECOMMENDED_MODELS[provider];
		setModelSections(rec.sections);
		setModelSynthesis(rec.synthesis);
		setModelFacets(rec.facets);
		await Promise.all([
			handleSave("insights.model_sections", rec.sections),
			handleSave("insights.model_synthesis", rec.synthesis),
			handleSave("insights.model_facets", rec.facets),
		]);
	}, [provider, handleSave]);

	const handleModelChange = useCallback(
		(key: string, setter: (v: string) => void) => (value: string) => {
			setter(value);
			handleSave(key, value);
		},
		[handleSave],
	);

	const handleProviderChange = useCallback(
		(id: ProviderId | "") => {
			const previousProvider = provider;
			setProvider(id);

			if (id !== previousProvider && previousProvider !== "") {
				setModelSections("");
				setModelSynthesis("");
				setModelFacets("");
				void (async () => {
					try {
						await Promise.all([
							onSave("insights.model_sections", ""),
							onSave("insights.model_synthesis", ""),
							onSave("insights.model_facets", ""),
						]);
					} catch {
						toast.error("Failed to clear model settings for the previous provider");
						refetch();
					}
				})();
			}

			setProviderOpen(false);
		},
		[onSave, provider, refetch],
	);

	// Status config
	const statusConfig = {
		not_configured: { color: "bg-zinc-400", label: "Not configured" },
		partial: { color: "bg-amber-400", label: "Partially configured" },
		ready: { color: "bg-emerald-400", label: "Ready" },
	};

	return (
		<section className="mb-6 mt-2">
			{/* Header */}
			<div className="flex items-center justify-between mb-1">
				<h3 className="text-sm font-semibold uppercase tracking-wider text-foreground/80 flex items-center gap-1.5">
					<Activity className="h-3.5 w-3.5" />
					Agent Insights
				</h3>
				<div className="flex items-center gap-1.5">
					<div className={cn("h-2 w-2 rounded-full", statusConfig[status].color)} />
					<span className="text-xs text-muted-foreground">
						{statusConfig[status].label}
					</span>
				</div>
			</div>
			<p className="text-xs text-foreground/60 mb-3">
				Configure LLM provider for the insights engine. Supports any LiteLLM-compatible provider.
			</p>

			{/* Main card */}
			<div className="rounded-lg border border-border bg-card p-5 space-y-5">
				{/* Provider selector */}
				<div>
					<label className="text-sm font-medium text-foreground block mb-2">Provider</label>
					<Popover open={providerOpen} onOpenChange={setProviderOpen}>
						<PopoverTrigger asChild>
							<Button
								variant="outline"
								role="combobox"
								aria-expanded={providerOpen}
								className={cn(
									"w-full max-w-xs justify-between h-9 text-sm",
									!provider && "text-muted-foreground",
								)}
							>
								{selectedProvider?.label || "Select provider..."}
								<ChevronsUpDown className="ml-2 h-3.5 w-3.5 shrink-0 opacity-50" />
							</Button>
						</PopoverTrigger>
						<PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
							<Command>
								<CommandInput placeholder="Search providers..." />
								<CommandList>
									<CommandEmpty>No provider found.</CommandEmpty>
									<CommandGroup>
										{PROVIDERS.map((p) => (
											<CommandItem
												key={p.id}
												value={p.label}
												onSelect={() => handleProviderChange(p.id)}
											>
												<Check
													className={cn(
														"mr-2 h-3.5 w-3.5",
														provider === p.id ? "opacity-100" : "opacity-0",
													)}
												/>
												{p.label}
											</CommandItem>
										))}
									</CommandGroup>
								</CommandList>
							</Command>
						</PopoverContent>
					</Popover>
				</div>

				{/* API Key */}
				<div className="space-y-1.5">
					<label className="text-sm font-medium text-foreground">API Key</label>
					<div className="flex items-center gap-2">
						<div className="relative flex-1 max-w-md">
							<Input
								type={showApiKey ? "text" : "password"}
								value={apiKeyValue}
								onChange={(e) => setApiKeyValue(e.target.value)}
								placeholder={
									isKeySet("insights.api_key")
										? "Key is set, enter new value to replace"
										: "sk-ant-... or sk-... or Bedrock API key"
								}
								className="h-9 text-sm font-mono pr-9"
								onKeyDown={(e) => {
									if (e.key === "Enter") handleApiKeySave();
								}}
							/>
							<button
								type="button"
								className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
								onClick={() => setShowApiKey(!showApiKey)}
								tabIndex={-1}
							>
								{showApiKey ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
							</button>
						</div>
						<Button
							size="sm"
							variant="outline"
							className="h-9 px-3 text-xs"
							onClick={handleApiKeySave}
							disabled={!apiKeyValue || saving["insights.api_key"]}
						>
							{saving["insights.api_key"] ? (
								<Loader2 className="h-3.5 w-3.5 animate-spin" />
							) : (
								"Save"
							)}
						</Button>
						<Button
							size="sm"
							variant="outline"
							className="h-9 px-3 text-xs"
							onClick={handleTestConnection}
							disabled={testingConnection}
						>
							{testingConnection && (
								<Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
							)}
							Test Connection
						</Button>
						{isKeySet("insights.api_key") && (
							<Button
								size="sm"
								variant="ghost"
								className="h-9 px-2 text-xs text-destructive hover:text-destructive"
								onClick={() => onRevoke("insights.api_key")}
							>
								Revoke
							</Button>
						)}
					</div>
					{/* Test result banner */}
					{testResult && (
						<div
							className={cn(
								"rounded-md px-3 py-2 text-xs flex items-start gap-2",
								testResult.success
									? "bg-emerald-500/10 border border-emerald-500/20 text-emerald-700 dark:text-emerald-300"
									: "bg-destructive/10 border border-destructive/20 text-destructive",
							)}
						>
							{testResult.success ? (
								<>
									<Check className="h-3.5 w-3.5 mt-0.5 shrink-0" />
									<span>
										Connected to <span className="font-mono font-medium">{testResult.model}</span>
										{testResult.latency_ms != null && ` (${testResult.latency_ms}ms)`}
									</span>
								</>
							) : (
								<div className="space-y-0.5">
									<p className="font-medium">{testResult.error}</p>
									{testResult.hint && (
										<p className="text-muted-foreground">{testResult.hint}</p>
									)}
								</div>
							)}
						</div>
					)}
				</div>

	
				{/* Divider */}
				<div className="border-t border-border/50" />

				{/* Models heading */}
				<div className="space-y-1">
					<p className="text-sm font-medium text-foreground">Models</p>
					<p className="text-xs text-muted-foreground">
						Only Sections Model is required. Others fall back to it if left empty.
					</p>
				</div>

				{/* Model selectors - aligned grid */}
				<div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
					<ModelCombobox
						label="Sections Model"
						subtitle="Writes the detailed report. Use your best model."
						value={modelSections}
						onChange={handleModelChange("insights.model_sections", setModelSections)}
						suggestions={suggestions}
						placeholder="Required"
					/>
					<ModelCombobox
						label="Synthesis Model"
						subtitle="Aggregates patterns. Falls back to Sections if empty."
						value={modelSynthesis}
						onChange={handleModelChange("insights.model_synthesis", setModelSynthesis)}
						suggestions={suggestions}
						placeholder="Optional"
					/>
					<ModelCombobox
						label="Facets Model"
						subtitle="Scans each session. Runs many times, use cheapest."
						value={modelFacets}
						onChange={handleModelChange("insights.model_facets", setModelFacets)}
						suggestions={suggestions}
						placeholder="Optional"
					/>
				</div>

				{/* Use Recommended */}
				{showRecommended && (
					<Button
						variant="outline"
						size="sm"
						className="h-8 text-xs"
						onClick={handleUseRecommended}
						disabled={saving["insights.model_sections"]}
					>
						<Sparkles className="h-3.5 w-3.5 mr-1.5" />
						Use recommended models
					</Button>
				)}

				{/* Base URL - above advanced */}
				{showBaseUrl && (
					<div className="space-y-1.5">
						<label className="text-xs font-medium text-muted-foreground">
							Base URL
							{selectedProvider?.requiresBaseUrl ? (
								<span className="font-normal text-foreground ml-1">(required for {selectedProvider.label})</span>
							) : (
								<span className="font-normal ml-1">(optional)</span>
							)}
						</label>
						<Input
							value={apiBase}
							onChange={(e) => setApiBase(e.target.value)}
							placeholder={selectedProvider?.baseUrlHint || "https://..."}
							className="h-8 text-xs font-mono max-w-md"
							onBlur={() => {
								if (apiBase !== getEntryValue("insights.api_base")) {
									handleSave("insights.api_base", apiBase);
								}
							}}
							onKeyDown={(e) => {
								if (e.key === "Enter") handleSave("insights.api_base", apiBase);
							}}
						/>
					</div>
				)}

				{/* Advanced settings */}
				<details className="group rounded-md border border-border/70">
					<summary className="flex items-center gap-2 px-4 py-2.5 cursor-pointer select-none hover:bg-muted/30 transition-colors text-sm font-medium text-foreground/70">
						Advanced
					</summary>
					<div className="px-4 pb-4 pt-2 space-y-4 border-t border-border/50">
						<div className="flex items-center justify-between">
							<div>
								<p className="text-sm font-medium">Batch Processing</p>
								<p className="text-xs text-muted-foreground">
									Automatically generate reports on schedule
								</p>
							</div>
							<Switch
								checked={batchEnabled}
								onCheckedChange={(checked) => {
									setBatchEnabled(checked);
									handleSave("insights.batch_enabled", String(checked));
								}}
							/>
						</div>

						<div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
							<div className="space-y-1">
								<label className="text-xs text-muted-foreground">
									Batch Period (days)
								</label>
								<Input
									type="number"
									min={1}
									value={batchPeriod}
									onChange={(e) => setBatchPeriod(e.target.value)}
									className="h-8 text-sm"
									onBlur={() => {
										if (batchPeriod !== getEntryValue("insights.batch_period_days")) {
											handleSave("insights.batch_period_days", batchPeriod);
										}
									}}
								/>
							</div>
							<div className="space-y-1">
								<label className="text-xs text-muted-foreground">
									Min Sessions
								</label>
								<Input
									type="number"
									min={1}
									value={minSessions}
									onChange={(e) => setMinSessions(e.target.value)}
									className="h-8 text-sm"
									onBlur={() => {
										if (minSessions !== getEntryValue("insights.min_sessions")) {
											handleSave("insights.min_sessions", minSessions);
										}
									}}
								/>
							</div>
							<div className="space-y-1">
								<label className="text-xs text-muted-foreground">
									Max Facet Calls
								</label>
								<Input
									type="number"
									min={1}
									value={maxFacetCalls}
									onChange={(e) => setMaxFacetCalls(e.target.value)}
									className="h-8 text-sm"
									onBlur={() => {
										if (maxFacetCalls !== getEntryValue("insights.facet_max_calls")) {
											handleSave("insights.facet_max_calls", maxFacetCalls);
										}
									}}
								/>
							</div>
							<div className="space-y-1">
								<label className="text-xs text-muted-foreground">
									Facet Concurrency
								</label>
								<Input
									type="number"
									min={1}
									value={facetConcurrency}
									onChange={(e) => setFacetConcurrency(e.target.value)}
									className="h-8 text-sm"
									onBlur={() => {
										if (facetConcurrency !== getEntryValue("insights.facet_concurrency")) {
											handleSave("insights.facet_concurrency", facetConcurrency);
										}
									}}
								/>
							</div>
						</div>
					</div>
				</details>
			</div>
		</section>
	);
}
