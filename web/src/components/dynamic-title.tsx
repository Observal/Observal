// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 dexterhere-2k <deepakmirchandani.ai28@jecrc.ac.in>
// SPDX-License-Identifier: AGPL-3.0-only


import { useEffect } from "react";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";

export function DynamicTitle() {
  const { brandingAppName, brandingLogo } = useDeploymentConfig();

  useEffect(() => {
    document.title = brandingAppName || "Observal";
  }, [brandingAppName]);

  useEffect(() => {
    const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (link && brandingLogo) {
      link.href = brandingLogo;
    } else if (link) {
      link.href = "/icon.png";
    }
  }, [brandingLogo]);

  return null;
}
