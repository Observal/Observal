// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import Image from "next/image";
import {
	Settings,
	Plus,
	Pencil,
	Trash2,
	Save,
	X,
	Loader2,
	Info,
	Database,
	Activity,
	Shield,
	HelpCircle,
	Eye,
	Upload,
	RotateCcw,
	Palette,
	AlertTriangle,
	ShieldAlert,
} from "lucide-react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { useAdminSettings, useSystemWarnings } from "@/hooks/use-api";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";
import { useRoleGuard, hasMinRole } from "@/hooks/use-role-guard";
import type { AdminSetting, SystemWarning } from "@/lib/types";
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
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";

// Sensitive keys that should be masked in display
const SENSITIVE_KEYS = new Set([
	"saml.idp_x509_cert",
	"saml.sp_key_encryption_password",
]);

function maskValue(key: string, value: string): string {
	if (!SENSITIVE_KEYS.has(key)) return value;
	if (!value || value.length <= 4)
		return "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022";
	return "\u2022\u2022\u2022\u2022\u2022\u2022" + value.slice(-4);
}

/** Generate a helpful placeholder for the value input based on the key */
function getPlaceholder(key: string): string {
	const placeholders: Record<string, string> = {
		// Insights
		"insights.model_sections": "us.anthropic.claude-opus-4-6-v1",
		"insights.model_synthesis": "us.anthropic.claude-sonnet-4-6-v1",
		"insights.model_facets": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
		"insights.batch_enabled": "true",
		"insights.batch_period_days": "14",
		"insights.min_sessions": "5",
		"insights.facet_max_calls": "100",
		"insights.facet_concurrency": "25",
		// Deployment
		"deployment.sso_only": "true | false",
		"deployment.frontend_url": "https://app.example.com",
		"deployment.public_url": "https://api.example.com",
		"deployment.otlp_http_url": "https://otel.example.com",
		"deployment.cors_origins":
			"https://app.example.com,https://admin.example.com",
		// Security
		"security.allow_internal_git_urls": "true | false",
		"security.allow_draft_install": "true | false",
		"security.rate_limit_auth": "10/minute",
		"security.rate_limit_auth_strict": "5/minute",
		"security.trusted_proxy_ips": "10.0.0.1,10.0.0.2",
		// SAML
		"saml.idp_entity_id": "https://idp.example.com/entity",
		"saml.idp_sso_url": "https://idp.example.com/sso",
		"saml.idp_slo_url": "https://idp.example.com/slo",
		"saml.idp_x509_cert": "-----BEGIN CERTIFICATE-----...",
		"saml.idp_metadata_url": "https://idp.example.com/.well-known/metadata",
		"saml.sp_entity_id": "https://app.example.com/saml/metadata",
		"saml.sp_acs_url": "https://app.example.com/api/v1/sso/saml/acs",
		"saml.jit_provisioning": "true | false",
		"saml.default_role": "user | reviewer | admin",
		"saml.sp_key_encryption_password": "strong-random-password",
		// JWT
		"jwt.access_token_expire_minutes": "60",
		"jwt.refresh_token_expire_days": "7",
		"jwt.hooks_token_expire_minutes": "43200",
		// Resources
		"resource.db_pool_size": "10",
		"resource.db_max_overflow": "20",
		"resource.redis_max_connections": "50",
		"resource.redis_socket_timeout": "2.0",
		"resource.clickhouse_max_connections": "20",
		"resource.clickhouse_max_keepalive": "10",
		"resource.clickhouse_timeout": "10.0",
		"resource.skip_ddl_on_startup": "true | false",
		"resource.max_query_memory_mb": "400",
		"resource.group_by_spill_mb": "200",
		"resource.sort_spill_mb": "200",
		"resource.join_memory_mb": "100",
		// Data
		"data.retention_days": "90 (0 = no limit)",
		"data.cache_ttl_default": "30",
		"data.cache_ttl_dashboard": "60",
		"data.cache_ttl_otel": "15",
		// Observability
		"observability.log_level": "DEBUG | INFO | WARNING | ERROR",
		"observability.log_format": "json | console",
		"observability.enable_openapi": "true | false",
		"observability.enable_metrics": "true | false",
		// Misc
		"misc.git_mirror_base_path": "/var/lib/observal/mirrors",
	};
	return placeholders[key] || "Enter value...";
}


const ALLOWED_LOGO_TYPES = [
	"image/png",
	"image/svg+xml",
	"image/x-icon",
	"image/vnd.microsoft.icon",
	"image/jpeg",
	"image/webp",
];
const MAX_LOGO_SIZE = 2 * 1024 * 1024;

interface SettingDef {
	key: string;
	label: string;
	subtitle: string;
	tooltip: string;
}

interface SettingSection {
	title: string;
	icon: React.ReactNode;
	description?: string;
	danger?: boolean;
	settings: SettingDef[];
}

const SETTING_SECTIONS: SettingSection[] = [
	{
		title: "LLM / Eval Engine",
		icon: <Settings className="h-3.5 w-3.5" />,
		description:
			"Configure the LLM used for AI-powered insights and analysis.",
		settings: [
			{
				key: "eval.model_url",
				label: "Model Endpoint URL",
				subtitle: "OpenAI-compatible base URL for the LLM",
				tooltip:
					"The base URL of your LLM API. For Bedrock, leave blank (uses AWS SDK). For OpenAI-compatible APIs (vLLM, Ollama, Moonshot), provide the base URL like https://api.openai.com/v1",
			},
			{
				key: "eval.model_api_key",
				label: "Model API Key",
				subtitle: "Authentication key for the LLM endpoint",
				tooltip:
					"API key sent as Bearer token. For AWS Bedrock, leave blank and configure AWS credentials instead. For OpenAI/Moonshot, use your API key (sk-...).",
			},
			{
				key: "eval.model_name",
				label: "Model Name",
				subtitle: "Model identifier passed to the API",
				tooltip:
					"The model ID to use. Examples: us.anthropic.claude-haiku-4-5-20251001-v1:0 (Bedrock), gpt-4o (OpenAI), kimi-k2.5-preview (Moonshot).",
			},
			{
				key: "eval.model_provider",
				label: "Model Provider",
				subtitle: "Which API protocol to use",
				tooltip:
					"Set to 'bedrock' for AWS Bedrock Converse API, 'openai' for OpenAI-compatible APIs, 'moonshot' for Kimi. Leave blank to auto-detect from model name.",
			},
			{
				key: "eval.aws_region",
				label: "AWS Region",
				subtitle: "Region for Bedrock API calls",
				tooltip:
					"AWS region where Bedrock models are available. Common: us-east-1, us-west-2, eu-west-1. Only used when provider is bedrock.",
			},
			{
				key: "eval.aws_access_key_id",
				label: "AWS Access Key ID",
				subtitle: "IAM access key for Bedrock",
				tooltip:
					"AWS IAM access key with bedrock:InvokeModel permission. Leave blank to use instance role / ECS task role / environment credentials.",
			},
			{
				key: "eval.aws_secret_access_key",
				label: "AWS Secret Access Key",
				subtitle: "IAM secret key for Bedrock",
				tooltip:
					"The secret key paired with the access key ID. Stored encrypted. Leave blank for instance role authentication.",
			},
			{
				key: "eval.aws_session_token",
				label: "AWS Session Token",
				subtitle: "Temporary credentials token (optional)",
				tooltip:
					"Only needed for temporary/assumed-role credentials (e.g., from STS AssumeRole). Leave blank for permanent IAM keys or instance roles.",
			},
		],
	},
	{
		title: "Agent Insights",
		icon: <Activity className="h-3.5 w-3.5" />,
		description:
			"Per-model overrides and batch processing for the insights engine. Requires 'insights' license feature.",
		settings: [
			{
				key: "insights.model_sections",
				label: "Sections Model",
				subtitle: "Model for detailed narrative report sections",
				tooltip:
					"A capable model (e.g., Claude Opus) used for writing detailed insight sections. Falls back to the base model if blank. Use a high-quality model here for best report quality.",
			},
			{
				key: "insights.model_synthesis",
				label: "Synthesis Model",
				subtitle: "Model for aggregating and summarizing insights",
				tooltip:
					"Model used for cross-user synthesis and strategic recommendations. Sonnet-class models offer good balance of quality and cost. Falls back to the base model.",
			},
			{
				key: "insights.model_facets",
				label: "Facets Model",
				subtitle: "Model for per-session facet extraction",
				tooltip:
					"Model used for extracting structured facets from individual sessions. Can be a smaller/cheaper model (e.g., Haiku) since it processes many sessions. Falls back to the base model.",
			},
			{
				key: "insights.batch_enabled",
				label: "Batch Processing",
				subtitle: "Enable automatic insight report generation",
				tooltip:
					"When true, the system automatically generates insight reports on a schedule for agents with enough new sessions. Disable to only generate reports manually.",
			},
			{
				key: "insights.batch_period_days",
				label: "Batch Period",
				subtitle: "Days between automatic report runs",
				tooltip:
					"How often to check for and generate new reports. Default 14 days. Shorter periods = more reports but higher LLM cost.",
			},
			{
				key: "insights.min_sessions",
				label: "Minimum Sessions",
				subtitle: "Sessions required to trigger a report",
				tooltip:
					"An agent needs at least this many new sessions since the last report before a new one is generated. Prevents thin reports with insufficient data.",
			},
			{
				key: "insights.facet_max_calls",
				label: "Max Facet Calls",
				subtitle: "LLM call limit per report for facet extraction",
				tooltip:
					"Maximum number of LLM calls for extracting facets in a single report. Higher = more thorough but slower and costlier. Default 100.",
			},
			{
				key: "insights.facet_concurrency",
				label: "Facet Concurrency",
				subtitle: "Parallel LLM calls for facet extraction",
				tooltip:
					"How many facet extraction calls to run in parallel. Higher = faster but more API load. Keep below your provider's rate limit. Default 25.",
			},
		],
	},
	{
		title: "Deployment",
		icon: <Shield className="h-3.5 w-3.5" />,
		description:
			"Core deployment configuration. Changes may affect authentication and access.",
		danger: true,
		settings: [
			{
				key: "deployment.sso_only",
				label: "SSO Only Mode",
				subtitle: "Disable all password-based authentication",
				tooltip:
					"When enabled, password login, registration, and admin password reset are all blocked. Users must authenticate via OAuth/OIDC SSO. Ensure OAuth is configured before enabling or you will lock everyone out.",
			},
			{
				key: "deployment.frontend_url",
				label: "Frontend URL",
				subtitle: "Base URL where users access the web UI",
				tooltip:
					"Used for OAuth redirect URIs, SAML ACS URLs, device auth flows, and email links. Must exactly match what users type in their browser (including https:// and port if non-standard).",
			},
			{
				key: "deployment.public_url",
				label: "Public API URL",
				subtitle: "Externally-reachable URL of this API server",
				tooltip:
					"Used for OTLP endpoint discovery and CLI auto-configuration. Leave blank to auto-detect from incoming request headers. Set explicitly when behind a reverse proxy with a different external hostname.",
			},
			{
				key: "deployment.otlp_http_url",
				label: "OTLP Endpoint Override",
				subtitle: "Custom OpenTelemetry collector URL",
				tooltip:
					"If your OTLP ingestion runs on a different host/port from the main API (e.g., a dedicated collector), set it here. Otherwise defaults to the public API URL.",
			},
			{
				key: "deployment.cors_origins",
				label: "CORS Origins",
				subtitle: "Allowed cross-origin request origins",
				tooltip:
					"Comma-separated list of origins allowed to make browser requests to the API. Typically just your frontend URL. Example: https://app.example.com,https://admin.example.com",
			},
		],
	},
	{
		title: "Security",
		icon: <Shield className="h-3.5 w-3.5" />,
		description:
			"Security policies and rate limiting. Misconfiguration can expose the instance.",
		danger: true,
		settings: [
			{
				key: "security.allow_internal_git_urls",
				label: "Allow Internal Git URLs",
				subtitle: "Bypass SSRF protection for private networks",
				tooltip:
					"By default, git clone rejects URLs resolving to private/internal IPs (10.x, 172.16.x, 192.168.x) to prevent SSRF attacks. Enable ONLY if you run a self-hosted GitLab/GitHub Enterprise/Gitea on an internal network.",
			},
			{
				key: "security.allow_draft_install",
				label: "Allow Draft Install",
				subtitle: "Let owners install their own unapproved agents",
				tooltip:
					"When enabled, agent creators can install their own agents before admin review/approval. Only enable for local development or trusted self-hosted testing workflows. Disabled by default for security.",
			},
			{
				key: "security.rate_limit_auth",
				label: "Auth Rate Limit",
				subtitle: "Max login attempts per IP per minute",
				tooltip:
					"Format: N/minute or N/second. Applied to login, token, and refresh endpoints. Protects against credential brute-force attacks. Default: 10/minute.",
			},
			{
				key: "security.rate_limit_auth_strict",
				label: "Strict Auth Rate Limit",
				subtitle: "Limit for sensitive operations (reset, register)",
				tooltip:
					"Tighter rate limit for password reset, registration, and other sensitive operations. Should be stricter than the general auth limit. Default: 5/minute.",
			},
			{
				key: "security.trusted_proxy_ips",
				label: "Trusted Proxy IPs",
				subtitle: "IPs whose X-Forwarded-For header is trusted",
				tooltip:
					"Comma-separated list of proxy/load-balancer IPs. Only these IPs' X-Forwarded-For headers are used for rate limiting. Without this, the direct TCP socket IP is used (safest default). Set to your ALB/nginx IP.",
			},
		],
	},
	{
		title: "SAML 2.0 SSO",
		icon: <Shield className="h-3.5 w-3.5" />,
		description:
			"SAML identity provider configuration. Requires 'saml' license feature.",
		danger: true,
		settings: [
			{
				key: "saml.idp_entity_id",
				label: "IdP Entity ID",
				subtitle: "Identity Provider's unique identifier",
				tooltip:
					"The entity ID from your SAML IdP metadata. Usually a URL like https://idp.example.com/entity. Found in your IdP's SAML configuration or metadata XML.",
			},
			{
				key: "saml.idp_sso_url",
				label: "IdP SSO URL",
				subtitle: "Single Sign-On endpoint",
				tooltip:
					"The URL where Observal redirects users to authenticate. Found in your IdP's SAML metadata as the SingleSignOnService Location with HTTP-Redirect binding.",
			},
			{
				key: "saml.idp_slo_url",
				label: "IdP SLO URL",
				subtitle: "Single Logout endpoint (optional)",
				tooltip:
					"The URL for SAML Single Logout. When set, logging out of Observal also logs out of the IdP. Leave blank to disable federated logout.",
			},
			{
				key: "saml.idp_x509_cert",
				label: "IdP Certificate",
				subtitle: "X.509 certificate for signature verification",
				tooltip:
					"The IdP's public X.509 certificate in PEM format. Used to verify SAML assertion signatures. Copy from your IdP's metadata or certificate download page.",
			},
			{
				key: "saml.idp_metadata_url",
				label: "IdP Metadata URL",
				subtitle: "Auto-configure from metadata endpoint",
				tooltip:
					"URL to your IdP's SAML metadata XML. If provided, entity ID, SSO URL, and certificate can be auto-populated from this URL. Useful for IdPs that rotate certificates.",
			},
			{
				key: "saml.sp_entity_id",
				label: "SP Entity ID",
				subtitle: "This application's SAML identifier",
				tooltip:
					"The entity ID that identifies Observal to your IdP. Typically your app's metadata URL, e.g., https://app.example.com/api/v1/sso/saml/metadata. Must match what's configured in your IdP.",
			},
			{
				key: "saml.sp_acs_url",
				label: "SP ACS URL",
				subtitle: "Assertion Consumer Service endpoint",
				tooltip:
					"The URL where your IdP sends SAML responses after authentication. Must be: https://YOUR_DOMAIN/api/v1/sso/saml/acs. Register this URL in your IdP.",
			},
			{
				key: "saml.jit_provisioning",
				label: "JIT Provisioning",
				subtitle: "Auto-create users on first SAML login",
				tooltip:
					"When enabled, users who authenticate via SAML are automatically created in Observal if they don't already exist. Disable to require pre-provisioning (e.g., via SCIM).",
			},
			{
				key: "saml.default_role",
				label: "Default Role",
				subtitle: "Role assigned to JIT-provisioned users",
				tooltip:
					"The role given to users created via JIT provisioning. Options: user, reviewer, admin. Most deployments should use 'user' and promote manually.",
			},
			{
				key: "saml.sp_key_encryption_password",
				label: "SP Key Password",
				subtitle: "Password to encrypt the SP private key at rest",
				tooltip:
					"Used to encrypt the auto-generated SP private key stored in the database. Set a strong random password. If blank, the key is stored unencrypted (not recommended for production).",
			},
		],
	},
	{
		title: "JWT Token Expiry",
		icon: <Settings className="h-3.5 w-3.5" />,
		description:
			"Token lifetime settings. Shorter values improve security but increase re-authentication frequency.",
		settings: [
			{
				key: "jwt.access_token_expire_minutes",
				label: "Access Token Lifetime",
				subtitle: "Minutes before access tokens expire",
				tooltip:
					"How long an access token is valid. After expiry, the client must use a refresh token to get a new one. Shorter = more secure but more refresh requests. Default: 60 minutes.",
			},
			{
				key: "jwt.refresh_token_expire_days",
				label: "Refresh Token Lifetime",
				subtitle: "Days before refresh tokens expire",
				tooltip:
					"How long a refresh token is valid. After expiry, users must re-authenticate fully (login again). Shorter = more secure but users log in more often. Default: 7 days.",
			},
			{
				key: "jwt.hooks_token_expire_minutes",
				label: "Hooks Token Lifetime",
				subtitle: "Minutes before OTEL hook tokens expire",
				tooltip:
					"Lifetime for long-lived tokens used by OTEL telemetry hooks. These tokens can't be refreshed mid-session, so they need to be long-lived. Default: 43200 minutes (30 days).",
			},
		],
	},
	{
		title: "Resource Tuning",
		icon: <Database className="h-3.5 w-3.5" />,
		description:
			"Connection pool sizes and query limits. Some changes may require restart.",
		settings: [
			{
				key: "resource.db_pool_size",
				label: "DB Pool Size",
				subtitle: "PostgreSQL connection pool size",
				tooltip:
					"Number of persistent database connections maintained. Increase for high-traffic deployments. Each connection uses ~5MB RAM. Default: 10.",
			},
			{
				key: "resource.db_max_overflow",
				label: "DB Max Overflow",
				subtitle: "Extra connections allowed beyond pool size",
				tooltip:
					"Temporary connections created when the pool is exhausted. These are closed after use. Total max connections = pool_size + max_overflow. Default: 20.",
			},
			{
				key: "resource.redis_max_connections",
				label: "Redis Max Connections",
				subtitle: "Maximum Redis connection pool size",
				tooltip:
					"Maximum number of concurrent Redis connections. Increase if you see connection timeout errors under load. Default: 50.",
			},
			{
				key: "resource.redis_socket_timeout",
				label: "Redis Timeout",
				subtitle: "Socket timeout in seconds for Redis",
				tooltip:
					"How long to wait for a Redis response before timing out. Increase if Redis is on a high-latency network. Too high = slow failure detection. Default: 2.0.",
			},
			{
				key: "resource.clickhouse_max_connections",
				label: "ClickHouse Max Connections",
				subtitle: "Maximum concurrent ClickHouse connections",
				tooltip:
					"Maximum HTTP connections to ClickHouse. Increase for heavy analytics workloads. Default: 20.",
			},
			{
				key: "resource.clickhouse_max_keepalive",
				label: "ClickHouse Keepalive",
				subtitle: "Persistent connections kept alive",
				tooltip:
					"Number of ClickHouse connections kept open between requests. Reduces connection overhead for frequent queries. Default: 10.",
			},
			{
				key: "resource.clickhouse_timeout",
				label: "ClickHouse Query Timeout",
				subtitle: "Seconds before a query is killed",
				tooltip:
					"Maximum time a single ClickHouse query can run before being cancelled. Prevents runaway queries from consuming resources. Default: 10.0.",
			},
			{
				key: "resource.skip_ddl_on_startup",
				label: "Skip DDL on Startup",
				subtitle: "Skip database schema creation on boot",
				tooltip:
					"Set to true when using a dedicated init container for schema migrations. Prevents the API server from running CREATE TABLE statements on startup. Default: false.",
			},
			{
				key: "resource.max_query_memory_mb",
				label: "Query Memory Limit",
				subtitle: "Max MB per ClickHouse query",
				tooltip:
					"Maximum memory a single ClickHouse query can use before it is killed. Set below your container memory limit to prevent OOM crashes. Applied live — no restart needed. Default: 400.",
			},
			{
				key: "resource.group_by_spill_mb",
				label: "GROUP BY Spill Threshold",
				subtitle: "MB before aggregation spills to disk",
				tooltip:
					"When a GROUP BY aggregation exceeds this memory, ClickHouse spills to disk. Lower values = less peak RAM but slower large aggregations. Default: 200.",
			},
			{
				key: "resource.sort_spill_mb",
				label: "ORDER BY Spill Threshold",
				subtitle: "MB before sorting spills to disk",
				tooltip:
					"When an ORDER BY sort exceeds this memory, ClickHouse spills to disk. Prevents large result sets from consuming all available memory. Default: 200.",
			},
			{
				key: "resource.join_memory_mb",
				label: "JOIN Memory Limit",
				subtitle: "MB before JOIN falls back to partial-merge",
				tooltip:
					"Maximum memory for hash JOIN operations. When exceeded, ClickHouse falls back to a slower partial-merge join that uses less memory. Default: 100.",
			},
		],
	},
	{
		title: "Data & Retention",
		icon: <Database className="h-3.5 w-3.5" />,
		description: "Data retention policies and cache TTLs.",
		settings: [
			{
				key: "data.retention_days",
				label: "Data Retention",
				subtitle: "Maximum age for telemetry data in days",
				tooltip:
					"Global ceiling for how long traces, spans, and scores are kept. After this many days, data is permanently deleted. Set to 0 to keep data forever. Per-org retention cannot exceed this. Default: 90.",
			},
			{
				key: "data.cache_ttl_default",
				label: "Default Cache TTL",
				subtitle: "Seconds before cached responses refresh",
				tooltip:
					"How long general API responses are cached in Redis. Lower = more real-time data but higher database load. Applies to most list/detail endpoints. Default: 30.",
			},
			{
				key: "data.cache_ttl_dashboard",
				label: "Dashboard Cache TTL",
				subtitle: "Seconds for dashboard analytics cache",
				tooltip:
					"Cache duration for expensive dashboard aggregation queries. Longer = less load on ClickHouse but slightly stale charts. Default: 60.",
			},
			{
				key: "data.cache_ttl_otel",
				label: "OTEL Cache TTL",
				subtitle: "Seconds for trace/session list cache",
				tooltip:
					"Cache duration for OpenTelemetry session and trace list endpoints. Short to keep live monitoring fresh. Default: 15.",
			},
		],
	},
	{
		title: "Observability",
		icon: <Activity className="h-3.5 w-3.5" />,
		description: "Logging and metrics configuration.",
		settings: [
			{
				key: "observability.log_level",
				label: "Log Level",
				subtitle: "Server log verbosity",
				tooltip:
					"Controls how much the server logs. DEBUG = every request (very noisy). INFO = normal operations (recommended for production). WARNING/ERROR = only problems. Takes effect on restart.",
			},
			{
				key: "observability.log_format",
				label: "Log Format",
				subtitle: "Structured JSON or human-readable console",
				tooltip:
					"'json' outputs structured logs ideal for log aggregators (Datadog, Loki, CloudWatch). 'console' outputs colored human-readable logs ideal for local development.",
			},
			{
				key: "observability.enable_openapi",
				label: "Enable OpenAPI",
				subtitle: "Expose /docs, /redoc, and /openapi.json",
				tooltip:
					"When true, exposes interactive API documentation at /docs (Swagger UI) and /redoc. Automatically enabled in local mode. Disable in production to reduce attack surface and hide API schema.",
			},
			{
				key: "observability.enable_metrics",
				label: "Enable Metrics",
				subtitle: "Expose Prometheus /metrics endpoint",
				tooltip:
					"When true, exposes a Prometheus-compatible metrics endpoint at /metrics for scraping. Enable if you use Prometheus/Grafana for infrastructure monitoring. Automatically enabled in local mode.",
			},
		],
	},
	{
		title: "Miscellaneous",
		icon: <Settings className="h-3.5 w-3.5" />,
		description: "Other system settings.",
		settings: [
			{
				key: "misc.git_mirror_base_path",
				label: "Git Mirror Path",
				subtitle: "Directory for cloned repo mirrors",
				tooltip:
					"Where git repos are cloned for MCP server analysis and component discovery. Set to a shared/persistent path for multi-instance deployments. Leave blank to use the system temp directory (/tmp).",
			},
		],
	},
];

const ALL_DEFAULT_SETTINGS = SETTING_SECTIONS.flatMap((s) => s.settings);

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
	const { data: systemWarnings } = useSystemWarnings();
	const {
		deploymentMode,
		ssoEnabled,
		samlEnabled,
		isLicensed,
		brandingLogo,
		brandingAppName,
		brandingWordmark,
	} = useDeploymentConfig();
	const [editingKey, setEditingKey] = useState<string | null>(null);
	const [editingValue, setEditingValue] = useState("");
	const [saving, setSaving] = useState(false);
	const [applyingResources, setApplyingResources] = useState(false);
	const [tracePrivacy, setTracePrivacy] = useState(false);
	const [tracePrivacyLoading, setTracePrivacyLoading] = useState(true);
	const [tracePrivacyToggling, setTracePrivacyToggling] = useState(false);
	const [registeredAgentsOnly, setRegisteredAgentsOnly] = useState(false);
	const [registeredAgentsOnlyLoading, setRegisteredAgentsOnlyLoading] =
		useState(() => hasMinRole(getUserRole(), "super_admin"));
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
	const fileInputRef = useRef<HTMLInputElement>(null);
	const wordmarkInputRef = useRef<HTMLInputElement>(null);

	const logoPreview = logoOverride !== undefined ? logoOverride : brandingLogo;
	const wordmarkPreview =
		wordmarkOverride !== undefined ? wordmarkOverride : brandingWordmark;
	const appNameDraft =
		appNameOverride !== undefined ? appNameOverride : brandingAppName || "";

	useEffect(() => {
		admin
			.getTracePrivacy()
			.then((res) => setTracePrivacy(res.trace_privacy))
			.catch(() => {})
			.finally(() => setTracePrivacyLoading(false));
		if (hasMinRole(getUserRole(), "super_admin")) {
			admin
				.getRegisteredAgentsOnly()
				.then((res) => setRegisteredAgentsOnly(res.registered_agents_only))
				.catch(() => {})
				.finally(() => setRegisteredAgentsOnlyLoading(false));
		}
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
			.catch(() => {})
			.finally(() => setRetentionLoading(false));
	}, []);

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

	const handleRegisteredAgentsOnlyToggle = useCallback(
		async (checked: boolean) => {
			setRegisteredAgentsOnlyToggling(true);
			try {
				const res = await admin.setRegisteredAgentsOnly(checked);
				setRegisteredAgentsOnly(res.registered_agents_only);
				toast.success(
					`Registered agents only ${res.registered_agents_only ? "enabled" : "disabled"}`,
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
			toast.success("Branding updated");
		} catch (e) {
			toast.error(e instanceof Error ? e.message : "Failed to save branding");
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
			toast.success("Branding reset to defaults");
		} catch (e) {
			toast.error(e instanceof Error ? e.message : "Failed to reset branding");
		} finally {
			setBrandingSaving(false);
		}
	}, [queryClient]);

	const hasBrandingChanges =
		logoPreview !== brandingLogo ||
		wordmarkPreview !== brandingWordmark ||
		appNameDraft.trim() !== (brandingAppName || "");

	const entries: { key: string; value: string }[] = (
		Array.isArray(settings)
			? settings.map((s: AdminSetting) => ({ key: s.key, value: s.value }))
			: Object.entries(settings ?? {}).map(([k, v]) => ({
					key: k,
					value: String(v),
				}))
	).filter((e) => !e.key.startsWith("branding."));


	const handleInlineSave = useCallback(async () => {
		if (!editingKey) return;
		setSaving(true);
		try {
			await admin.updateSetting(editingKey, { value: editingValue });
			toast.success(`Saved ${editingKey}`);
			setEditingKey(null);
			setEditingValue("");
			refetch();
		} catch (e) {
			toast.error(e instanceof Error ? e.message : "Failed to save");
		} finally {
			setSaving(false);
		}
	}, [editingKey, editingValue, refetch]);

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
			/>
			<div className="p-6 w-full mx-auto space-y-6">
				{/* Security warnings */}
				{systemWarnings && systemWarnings.length > 0 && (
					<section className="animate-in">
						<div className="space-y-2">
							{systemWarnings.map((w: SystemWarning) => (
								<div
									key={w.code}
									className={`rounded-md border px-4 py-3 flex items-start gap-3 ${
										w.level === "critical"
											? "border-destructive/40 bg-destructive/10"
											: "border-warning/40 bg-warning/10"
									}`}
								>
									{w.level === "critical" ? (
										<ShieldAlert className="h-4 w-4 mt-0.5 shrink-0 text-destructive" />
									) : (
										<AlertTriangle className="h-4 w-4 mt-0.5 shrink-0 text-warning" />
									)}
									<div>
										<p
											className={`text-sm font-medium ${w.level === "critical" ? "text-destructive" : "text-warning"}`}
										>
											{w.level === "critical" ? "Critical" : "Warning"}
										</p>
										<p className="text-xs text-muted-foreground mt-0.5">
											{w.message}
										</p>
									</div>
								</div>
							))}
						</div>
					</section>
				)}
				{/* System Overview */}
				<section className="animate-in">
					<h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
						System Overview
					</h3>
					<div className="rounded-md border border-border bg-card px-4 py-3 space-y-2">
						<div className="flex items-center justify-between py-1">
							<span className="text-xs text-muted-foreground">
								Deployment Mode
							</span>
							<span className="text-xs font-medium font-[family-name:var(--font-mono)]">
								{deploymentMode}
							</span>
						</div>
						<div className="flex items-center justify-between py-1 border-t border-border">
							<span className="text-xs text-muted-foreground">
								SSO (OAuth/OIDC)
							</span>
							<span
								className={`text-xs font-medium ${ssoEnabled ? "text-success" : "text-muted-foreground"}`}
							>
								{ssoEnabled ? "Enabled" : "Disabled"}
							</span>
						</div>
						<div className="flex items-center justify-between py-1 border-t border-border">
							<span className="text-xs text-muted-foreground">SAML SSO</span>
							<span
								className={`text-xs font-medium ${samlEnabled ? "text-success" : "text-muted-foreground"}`}
							>
								{samlEnabled ? "Configured" : "Not configured"}
							</span>
						</div>
					</div>
					{isLicensed && (
						<div className="flex items-start gap-2 mt-2 text-xs text-muted-foreground">
							<Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
							<span>
								Enterprise mode is active. Self-registration and password login
								are disabled.
							</span>
						</div>
					)}
				</section>

				{/* Branding */}
				<section className="animate-in">
					<h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3 flex items-center gap-1.5">
						<Palette className="h-3.5 w-3.5" />
						Branding
					</h3>
					<div className="rounded-md border border-border bg-card px-4 py-3 space-y-3">
						<p className="text-xs text-muted-foreground">
							PNG, SVG, ICO, JPEG, or WEBP. Max 2MB. Transparent images
							recommended for theme compatibility.
						</p>
						<div className="flex flex-wrap gap-4">
							{/* Logo icon */}
							<div className="space-y-1.5">
								<p className="text-xs font-medium">Icon</p>
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
										<Image
											src={logoPreview}
											alt="Icon"
											width={32}
											height={32}
											className="object-contain"
											unoptimized
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
								<div className="flex gap-1">
									<Button
										variant="ghost"
										size="sm"
										className="h-6 text-[11px] px-1.5"
										onClick={() => fileInputRef.current?.click()}
									>
										Upload
									</Button>
									{logoPreview && (
										<Button
											variant="ghost"
											size="sm"
											className="h-6 text-[11px] px-1.5 text-muted-foreground"
											onClick={() => setLogoOverride(null)}
										>
											Remove
										</Button>
									)}
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
										<Image
											src={wordmarkPreview}
											alt="Wordmark"
											width={96}
											height={24}
											className="h-6 max-w-24 object-contain"
											unoptimized
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
								<div className="flex gap-1">
									<Button
										variant="ghost"
										size="sm"
										className="h-6 text-[11px] px-1.5"
										onClick={() => wordmarkInputRef.current?.click()}
									>
										Upload
									</Button>
									{wordmarkPreview && (
										<Button
											variant="ghost"
											size="sm"
											className="h-6 text-[11px] px-1.5 text-muted-foreground"
											onClick={() => setWordmarkOverride(null)}
										>
											Remove
										</Button>
									)}
								</div>
							</div>
							{/* App name (text fallback) */}
							<div className="space-y-1.5">
								<p className="text-xs font-medium">
									App Name{" "}
									<span className="text-muted-foreground font-normal">
										(used when no wordmark)
									</span>
								</p>
								<Input
									value={appNameDraft}
									onChange={(e) => setAppNameOverride(e.target.value)}
									placeholder="Observal"
									maxLength={30}
									className="h-8 text-sm w-48"
								/>
								<p className="text-[11px] text-muted-foreground">
									{appNameDraft.length}/30
								</p>
							</div>
						</div>
						{/* Preview + actions */}
						<div className="flex items-center gap-4 pt-1 border-t border-border">
							<div className="rounded bg-sidebar px-3 py-2 inline-flex items-center gap-2">
								<div className="flex size-8 shrink-0 items-center justify-center">
									{logoPreview ? (
										<Image
											src={logoPreview}
											alt=""
											width={20}
											height={20}
											className="object-contain"
											unoptimized
										/>
									) : (
										<Image
											src="/observal-logo.svg"
											alt=""
											width={20}
											height={20}
											className="object-contain"
										/>
									)}
								</div>
								{wordmarkPreview ? (
									<Image
										src={wordmarkPreview}
										alt=""
										width={140}
										height={16}
										className="h-4 max-w-35 object-contain object-left"
										unoptimized
									/>
								) : (
									<span className="text-sm font-semibold tracking-tight font-display text-sidebar-foreground truncate max-w-35">
										{appNameDraft.trim() || "Observal"}
									</span>
								)}
							</div>
							<div className="flex items-center gap-2">
								<Button
									size="sm"
									className="h-7 text-xs"
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
										className="h-7 text-xs"
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

				{/* Trace Privacy */}
				<section className="animate-in">
					<h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3 flex items-center gap-1.5">
						<Eye className="h-3.5 w-3.5" />
						Trace Privacy
					</h3>
					<div className="rounded-md border border-border bg-card px-4 py-3">
						<div className="flex items-center justify-between">
							<div className="flex-1">
								<p className="text-sm font-medium">Restrict trace visibility</p>
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

				{/* Registered Agents Only — super_admin only */}
				{hasMinRole(getUserRole(), "super_admin") && (
					<section className="animate-in">
						<h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3 flex items-center gap-1.5">
							<Shield className="h-3.5 w-3.5" />
							Registered Agents Only
						</h3>
						<div className="rounded-md border border-border bg-card px-4 py-3">
							<div className="flex items-center justify-between">
								<div className="flex-1">
									<p className="text-sm font-medium">
										Only trace registered agents
									</p>
									<p className="text-xs text-muted-foreground mt-0.5">
										When enabled, only registered agents are traced.
										Unregistered agent telemetry is stored as metadata-only (no
										content payloads).
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

				{/* Data Retention — super_admin only */}
				{hasMinRole(getUserRole(), "super_admin") && (
					<section className="animate-in">
						<h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3 flex items-center gap-1.5">
							<Database className="h-3.5 w-3.5" />
							Data Retention
						</h3>
						<div className="rounded-md border border-border bg-card p-4 space-y-4">
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

				{isLoading ? (
					<TableSkeleton rows={5} cols={2} />
				) : isError ? (
					<ErrorState message={error?.message} onRetry={() => refetch()} />
				) : (
					<div className="animate-in space-y-6">
						{/* Add new setting form */}
						{/* Unified sections — each setting stays in its section */}
						<TooltipProvider delayDuration={300}>
							{SETTING_SECTIONS.filter((s) => !s.danger).map((section) => (
								<section key={section.title} className="mb-6">
									<h3 className="text-sm font-semibold uppercase tracking-wider text-foreground/80 mb-1 flex items-center gap-1.5">
										{section.icon}
										{section.title}
									</h3>
									{section.description && (
										<p className="text-xs text-foreground/60 mb-3">{section.description}</p>
									)}
									<div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
									{section.settings.map((d) => {
										const existing = entries.find((e) => e.key === d.key);
										const isEditing = editingKey === d.key;
										if (isEditing) {
											return (
												<div key={d.key} className="rounded-md border-2 border-primary/50 bg-card p-3">
													<span className="text-sm font-semibold text-foreground mb-2 block">{d.label}</span>
													<div className="flex items-center gap-2">
														<Input value={editingValue} onChange={(e) => setEditingValue(e.target.value)} placeholder={getPlaceholder(d.key)} className="h-8 text-sm flex-1 font-[family-name:var(--font-mono)]" autoFocus onKeyDown={(e) => { if (e.key === "Enter") handleInlineSave(); if (e.key === "Escape") { setEditingKey(null); setEditingValue(""); } }} />
														<Button size="sm" className="h-8" onClick={handleInlineSave} disabled={saving}>{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}</Button>
														<Button size="sm" variant="ghost" className="h-8" onClick={() => { setEditingKey(null); setEditingValue(""); }}><X className="h-3.5 w-3.5" /></Button>
													</div>
												</div>
											);
										}
										if (existing && existing.value) {
											return (
												<div key={d.key} className="rounded-md border-2 border-border bg-card p-3 relative">
													<div className="absolute right-2 top-2"><Tooltip><TooltipTrigger asChild><HelpCircle className="h-5 w-5 text-muted-foreground/40 hover:text-foreground transition-colors cursor-help" /></TooltipTrigger><TooltipContent side="left" className="max-w-[340px] text-sm leading-relaxed p-3">{d.tooltip}</TooltipContent></Tooltip></div>
													<span className="text-sm font-semibold text-foreground">{d.label}</span>
													<div className="flex items-center gap-2 mt-1.5">
														<span className="text-xs text-foreground/70 font-[family-name:var(--font-mono)] truncate flex-1">{SENSITIVE_KEYS.has(d.key) ? maskValue(d.key, existing.value) : existing.value}</span>
														<Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => { setEditingKey(d.key); setEditingValue(SENSITIVE_KEYS.has(d.key) ? "" : existing.value); }}><Pencil className="h-3 w-3 text-muted-foreground" /></Button>
														<Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={async () => { await admin.updateSetting(d.key, { value: "" }); refetch(); toast.success(`Cleared ${d.label}`); }}><Trash2 className="h-3 w-3 text-muted-foreground hover:text-destructive" /></Button>
													</div>
												</div>
											);
										}
										return (
											<button key={d.key} type="button" onClick={() => { setEditingKey(d.key); setEditingValue(""); }} className="text-left rounded-md border-2 border-dashed border-border/80 p-3 hover:border-primary/40 hover:bg-background transition-colors relative">
												<div className="absolute right-2 top-2"><Tooltip><TooltipTrigger asChild onClick={(e) => e.stopPropagation()}><HelpCircle className="h-5 w-5 text-muted-foreground/40 hover:text-foreground transition-colors cursor-help" /></TooltipTrigger><TooltipContent side="left" className="max-w-[340px] text-sm leading-relaxed p-3">{d.tooltip}</TooltipContent></Tooltip></div>
												<span className="text-sm font-semibold text-foreground/60">+ {d.label}</span>
											</button>
										);
									})}
									</div>
								</section>
							))}

							{/* Danger Zone */}
							{SETTING_SECTIONS.some((s) => s.danger) && (
								<section className="mt-8">
									<div className="border-t-2 border-amber-500/30 pt-6">
										<h2 className="text-sm font-semibold text-amber-600 dark:text-amber-400 flex items-center gap-2 mb-1">
											<AlertTriangle className="h-4 w-4" />
											Danger Zone
										</h2>
										<p className="text-xs text-foreground/60 mb-4">These settings can affect authentication, security, and data integrity.</p>
										<div className="space-y-4">
											{SETTING_SECTIONS.filter((s) => s.danger).map((section) => (
												<details key={section.title} className="group rounded-md border-l-4 border-amber-500/60 border-2 border-border/70 bg-card">
													<summary className="flex items-center gap-2 px-4 py-3 cursor-pointer select-none hover:bg-muted/30 transition-colors">
														{section.icon}
														<span className="text-sm font-semibold text-foreground/80 flex-1">{section.title}</span>
														<span className="text-[10px] text-amber-600 dark:text-amber-400 font-medium">CAUTION</span>
													</summary>
													<div className="px-4 pb-4 pt-1">
														{section.description && (
															<p className="text-xs text-foreground/60 mb-3">{section.description}</p>
														)}
														<div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
															{section.settings.map((d) => {
														const existing = entries.find((e) => e.key === d.key);
														const isEditing = editingKey === d.key;
														if (isEditing) {
															return (
																<div key={d.key} className="rounded-md border-2 border-primary/50 bg-card p-3">
																	<span className="text-sm font-semibold text-foreground mb-2 block">{d.label}</span>
																	<div className="flex items-center gap-2">
																		<Input value={editingValue} onChange={(e) => setEditingValue(e.target.value)} placeholder={getPlaceholder(d.key)} className="h-8 text-sm flex-1 font-[family-name:var(--font-mono)]" autoFocus onKeyDown={(e) => { if (e.key === "Enter") handleInlineSave(); if (e.key === "Escape") { setEditingKey(null); setEditingValue(""); } }} />
																		<Button size="sm" className="h-8" onClick={handleInlineSave} disabled={saving}>{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}</Button>
																		<Button size="sm" variant="ghost" className="h-8" onClick={() => { setEditingKey(null); setEditingValue(""); }}><X className="h-3.5 w-3.5" /></Button>
																	</div>
																</div>
															);
														}
														if (existing && existing.value) {
															return (
																<div key={d.key} className="rounded-md border-2 border-border bg-card p-3 relative">
																	<div className="absolute right-2 top-2"><Tooltip><TooltipTrigger asChild><HelpCircle className="h-5 w-5 text-muted-foreground/40 hover:text-foreground transition-colors cursor-help" /></TooltipTrigger><TooltipContent side="left" className="max-w-[340px] text-sm leading-relaxed p-3">{d.tooltip}</TooltipContent></Tooltip></div>
																	<span className="text-sm font-semibold text-foreground">{d.label}</span>
																	<div className="flex items-center gap-2 mt-1.5">
																		<span className="text-xs text-foreground/70 font-[family-name:var(--font-mono)] truncate flex-1">{SENSITIVE_KEYS.has(d.key) ? maskValue(d.key, existing.value) : existing.value}</span>
																		<Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => { setEditingKey(d.key); setEditingValue(SENSITIVE_KEYS.has(d.key) ? "" : existing.value); }}><Pencil className="h-3 w-3 text-muted-foreground" /></Button>
																		<Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={async () => { await admin.updateSetting(d.key, { value: "" }); refetch(); toast.success(`Cleared ${d.label}`); }}><Trash2 className="h-3 w-3 text-muted-foreground hover:text-destructive" /></Button>
																	</div>
																</div>
															);
														}
														return (
															<button key={d.key} type="button" onClick={() => { setEditingKey(d.key); setEditingValue(""); }} className="text-left rounded-md border-2 border-dashed border-border/80 p-3 hover:border-primary/40 hover:bg-background transition-colors relative">
																<div className="absolute right-2 top-2"><Tooltip><TooltipTrigger asChild onClick={(e) => e.stopPropagation()}><HelpCircle className="h-5 w-5 text-muted-foreground/40 hover:text-foreground transition-colors cursor-help" /></TooltipTrigger><TooltipContent side="left" className="max-w-[340px] text-sm leading-relaxed p-3">{d.tooltip}</TooltipContent></Tooltip></div>
																<span className="text-sm font-semibold text-foreground/60">+ {d.label}</span>
															</button>
														);
															})}
														</div>
													</div>
												</details>
											))}
										</div>
									</div>
								</section>
							)}
						</TooltipProvider>
					</div>
				)}
			</div>
		</>
	);
}
