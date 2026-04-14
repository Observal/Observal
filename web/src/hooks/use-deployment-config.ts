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
    samlEnabled: data?.saml_enabled ?? false,
    evalConfigured: data?.eval_configured ?? false,
    loading: isLoading,
  };
}
