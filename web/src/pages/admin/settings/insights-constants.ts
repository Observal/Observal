// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

export type ProviderId =
	| "anthropic"
	| "openai"
	| "bedrock"
	| "gemini"
	| "azure"
	| "ollama"
	| "groq"
	| "mistral"
	| "together"
	| "deepseek"
	| "other";

export interface ProviderOption {
	id: ProviderId;
	label: string;
	requiresBaseUrl: boolean;
	baseUrlHint?: string;
	hasRecommendations: boolean;
}

export interface ModelSuggestion {
	id: string;
	label: string;
	tier: "primary" | "fast";
}

export type InsightsStatus = "not_configured" | "partial" | "ready";

export const PROVIDERS: ProviderOption[] = [
	{
		id: "anthropic",
		label: "Anthropic",
		requiresBaseUrl: false,
		hasRecommendations: true,
	},
	{
		id: "openai",
		label: "OpenAI",
		requiresBaseUrl: false,
		hasRecommendations: true,
	},
	{
		id: "bedrock",
		label: "AWS Bedrock",
		requiresBaseUrl: false,
		baseUrlHint: "https://bedrock-runtime.<region>.amazonaws.com",
		hasRecommendations: true,
	},
	{
		id: "gemini",
		label: "Google Gemini",
		requiresBaseUrl: false,
		hasRecommendations: true,
	},
	{
		id: "azure",
		label: "Azure OpenAI",
		requiresBaseUrl: true,
		baseUrlHint: "https://<instance>.openai.azure.com",
		hasRecommendations: false,
	},
	{
		id: "ollama",
		label: "Ollama",
		requiresBaseUrl: true,
		baseUrlHint: "http://localhost:11434",
		hasRecommendations: false,
	},
	{
		id: "groq",
		label: "Groq",
		requiresBaseUrl: false,
		hasRecommendations: false,
	},
	{
		id: "mistral",
		label: "Mistral",
		requiresBaseUrl: false,
		hasRecommendations: false,
	},
	{
		id: "together",
		label: "Together AI",
		requiresBaseUrl: false,
		hasRecommendations: false,
	},
	{
		id: "deepseek",
		label: "Deepseek",
		requiresBaseUrl: false,
		hasRecommendations: false,
	},
	{
		id: "other",
		label: "Other",
		requiresBaseUrl: true,
		baseUrlHint: "https://your-provider.example.com/v1",
		hasRecommendations: false,
	},
];

export const PROVIDER_MODELS: Record<string, ModelSuggestion[]> = {
	anthropic: [
		{ id: "anthropic/claude-sonnet-4-6", label: "Claude Sonnet 4.6", tier: "primary" },
		{ id: "anthropic/claude-opus-4-7", label: "Claude Opus 4.7", tier: "primary" },
		{ id: "anthropic/claude-sonnet-4-5", label: "Claude Sonnet 4.5", tier: "primary" },
		{ id: "anthropic/claude-haiku-4-5-20251001", label: "Claude Haiku 4.5", tier: "fast" },
	],
	openai: [
		{ id: "openai/gpt-4o", label: "GPT-4o", tier: "primary" },
		{ id: "openai/o3", label: "O3", tier: "primary" },
		{ id: "openai/gpt-4o-mini", label: "GPT-4o Mini", tier: "fast" },
		{ id: "openai/o4-mini", label: "O4 Mini", tier: "fast" },
	],
	bedrock: [
		{ id: "bedrock/global.anthropic.claude-opus-4-6-v1", label: "Claude Opus 4.6 (Global)", tier: "primary" },
		{ id: "bedrock/global.anthropic.claude-opus-4-5-20251101-v1:0", label: "Claude Opus 4.5 (Global)", tier: "primary" },
		{ id: "bedrock/us.anthropic.claude-sonnet-4-6-v1", label: "Claude Sonnet 4.6 (US only)", tier: "primary" },
		{ id: "bedrock/us.anthropic.claude-opus-4-6-v1", label: "Claude Opus 4.6 (US only)", tier: "primary" },
		{ id: "bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0", label: "Claude Haiku 4.5 (Global)", tier: "fast" },
		{ id: "bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0", label: "Claude Haiku 4.5 (US only)", tier: "fast" },
		{ id: "bedrock/us.amazon.nova-pro-v1:0", label: "Amazon Nova Pro (US only)", tier: "primary" },
		{ id: "bedrock/us.amazon.nova-lite-v1:0", label: "Amazon Nova Lite (US only)", tier: "fast" },
	],
	gemini: [
		{ id: "gemini/gemini-2.5-pro", label: "Gemini 2.5 Pro", tier: "primary" },
		{ id: "gemini/gemini-2.5-flash", label: "Gemini 2.5 Flash", tier: "fast" },
		{ id: "gemini/gemini-2.5-flash-lite", label: "Gemini 2.5 Flash Lite", tier: "fast" },
	],
	azure: [
		{ id: "azure/my-gpt4o-deployment", label: "GPT-4o (example)", tier: "primary" },
		{ id: "azure/my-gpt4o-mini-deployment", label: "GPT-4o Mini (example)", tier: "fast" },
	],
	ollama: [
		{ id: "ollama/llama3", label: "Llama 3", tier: "primary" },
		{ id: "ollama/mistral", label: "Mistral", tier: "primary" },
		{ id: "ollama/qwen2.5", label: "Qwen 2.5", tier: "fast" },
	],
	groq: [
		{ id: "groq/llama-3.3-70b-versatile", label: "Llama 3.3 70B", tier: "primary" },
		{ id: "groq/llama-3.1-8b-instant", label: "Llama 3.1 8B", tier: "fast" },
	],
	mistral: [
		{ id: "mistral/mistral-large-latest", label: "Mistral Large", tier: "primary" },
		{ id: "mistral/mistral-small-latest", label: "Mistral Small", tier: "fast" },
	],
	together: [
		{ id: "together_ai/meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", label: "Llama 3.1 70B Turbo", tier: "primary" },
	],
	deepseek: [
		{ id: "deepseek/deepseek-chat", label: "Deepseek Chat", tier: "primary" },
	],
};

export const RECOMMENDED_MODELS: Record<string, { sections: string; synthesis: string; facets: string }> = {
	anthropic: {
		sections: "anthropic/claude-sonnet-4-6",
		synthesis: "anthropic/claude-sonnet-4-6",
		facets: "anthropic/claude-haiku-4-5-20251001",
	},
	openai: {
		sections: "openai/gpt-4o",
		synthesis: "openai/gpt-4o",
		facets: "openai/gpt-4o-mini",
	},
	bedrock: {
		sections: "bedrock/global.anthropic.claude-opus-4-6-v1",
		synthesis: "bedrock/global.anthropic.claude-opus-4-6-v1",
		facets: "bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0",
	},
	gemini: {
		sections: "gemini/gemini-2.5-pro",
		synthesis: "gemini/gemini-2.5-pro",
		facets: "gemini/gemini-2.5-flash",
	},
};

export function detectProviderFromKey(apiKey: string): ProviderId | "" {
	if (!apiKey) return "";
	if (apiKey.startsWith("sk-ant-")) return "anthropic";
	if (apiKey.startsWith("sk-proj-") || apiKey.startsWith("sk-")) return "openai";
	if (apiKey.startsWith("AIza")) return "gemini";
	if (apiKey.startsWith("ABSK") || apiKey.startsWith("aws-")) return "bedrock";
	if (apiKey.startsWith("gsk_")) return "groq";
	return "";
}

export function detectProvider(modelValue: string): ProviderId | "" {
	if (!modelValue) return "";
	const prefix = modelValue.split("/")[0];
	const match = PROVIDERS.find((p) => p.id === prefix);
	if (match) return match.id;
	if (prefix === "together_ai") return "together";
	return "other";
}

export function getInsightsStatus(
	entries: { key: string; value: string; is_set?: boolean }[],
): InsightsStatus {
	const apiKeyEntry = entries.find((e) => e.key === "insights.api_key");
	const apiBaseEntry = entries.find((e) => e.key === "insights.api_base");
	const modelEntry = entries.find((e) => e.key === "insights.model_sections");

	const hasKey = apiKeyEntry?.is_set || (apiKeyEntry?.value && apiKeyEntry.value !== "");
	const hasBase = apiBaseEntry?.value && apiBaseEntry.value !== "";
	const hasModel = modelEntry?.value && modelEntry.value !== "";

	if (!hasKey && !hasBase && !hasModel) return "not_configured";
	if (!hasModel) return "partial";
	return "ready";
}
