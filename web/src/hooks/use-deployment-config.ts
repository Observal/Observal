// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { useQuery } from "@tanstack/react-query";
import { config, type PublicConfig } from "@/lib/api";

export function useDeploymentConfig() {
	const { data, isLoading } = useQuery<PublicConfig>({
		queryKey: ["config", "public"],
		queryFn: config.public,
		staleTime: 5 * 60 * 1000, // cache for 5 minutes
		retry: 1,
	});

	return {
		deploymentMode: data?.deployment_mode ?? "local",
		ssoEnabled: data?.sso_enabled ?? false,
		ssoOnly: data?.sso_only ?? false,
		samlEnabled: data?.saml_enabled ?? false,
		insightsAvailable: data?.insights_available ?? false,
		execDashboardAvailable: data?.exec_dashboard_available ?? false,
		licensedFeatures: data?.licensed_features ?? [],
		isLicensed: (data?.licensed_features?.length ?? 0) > 0,
		brandingLogo: data?.branding_logo ?? null,
		brandingAppName: data?.branding_app_name ?? null,
		brandingWordmark: data?.branding_wordmark ?? null,
		loading: isLoading,
	};
}
