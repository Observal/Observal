// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

export type ProviderId = string;

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
	tier: "primary" | "fast" | "catalog";
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
		id: "together_ai",
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

export const RECOMMENDED_MODELS: Record<string, { sections: string; synthesis: string; facets: string }> = {
	anthropic: {
		sections: "anthropic/claude-opus-4-6",
		synthesis: "anthropic/claude-opus-4-6",
		facets: "anthropic/claude-haiku-4-5-20251001",
	},
	openai: {
		sections: "openai/gpt-5.2",
		synthesis: "openai/gpt-5.2",
		facets: "openai/gpt-5-mini",
	},
	bedrock: {
		sections: "bedrock/converse/global.anthropic.claude-opus-4-6-v1",
		synthesis: "bedrock/converse/global.anthropic.claude-opus-4-6-v1",
		facets: "bedrock/converse/global.anthropic.claude-haiku-4-5-20251001-v1:0",
	},
	gemini: {
		sections: "gemini/gemini-3-pro-preview",
		synthesis: "gemini/gemini-3-pro-preview",
		facets: "gemini/gemini-3-flash-preview",
	},
	vertex_ai: {
		sections: "vertex_ai/gemini-3-pro-preview",
		synthesis: "vertex_ai/gemini-3-pro-preview",
		facets: "vertex_ai/gemini-3-flash-preview",
	},
	azure: {
		sections: "azure/gpt-5.2",
		synthesis: "azure/gpt-5.2",
		facets: "azure/gpt-5-mini",
	},
	azure_ai: {
		sections: "azure_ai/claude-opus-4-6",
		synthesis: "azure_ai/claude-opus-4-6",
		facets: "azure_ai/claude-haiku-4-5",
	},
	mistral: {
		sections: "mistral/mistral-large-latest",
		synthesis: "mistral/mistral-large-latest",
		facets: "mistral/mistral-small-latest",
	},
	groq: {
		sections: "groq/llama-3.3-70b-versatile",
		synthesis: "groq/llama-3.3-70b-versatile",
		facets: "groq/llama-3.1-8b-instant",
	},
	deepseek: {
		sections: "deepseek/deepseek-v4-pro",
		synthesis: "deepseek/deepseek-v4-pro",
		facets: "deepseek/deepseek-v4-flash",
	},
	xai: {
		sections: "xai/grok-4.3",
		synthesis: "xai/grok-4.3",
		facets: "xai/grok-4-1-fast-non-reasoning",
	},
	together_ai: {
		sections: "together_ai/zai-org/GLM-4.7",
		synthesis: "together_ai/zai-org/GLM-4.7",
		facets: "together_ai/meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
	},
	openrouter: {
		sections: "openrouter/anthropic/claude-opus-4.6",
		synthesis: "openrouter/anthropic/claude-opus-4.6",
		facets: "openrouter/anthropic/claude-haiku-4.5",
	},
	fireworks_ai: {
		sections: "fireworks_ai/deepseek-v4-pro",
		synthesis: "fireworks_ai/deepseek-v4-pro",
		facets: "fireworks_ai/deepseek-v4-flash",
	},
	perplexity: {
		sections: "perplexity/anthropic/claude-opus-4-6",
		synthesis: "perplexity/anthropic/claude-opus-4-6",
		facets: "perplexity/sonar",
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
	if (!modelValue || !modelValue.includes("/")) return "";
	return modelValue.split("/")[0] || "";
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
