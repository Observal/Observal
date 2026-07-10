// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 dexterhere-2k <deepakmirchandani.ai28@jecrc.ac.in>
// SPDX-License-Identifier: Apache-2.0


import { useEffect } from "react";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";

export function DynamicTitle() {
  const { brandingAppName, brandingLogo } = useDeploymentConfig();

  useEffect(() => {
    document.title = brandingAppName || "Observal";
  }, [brandingAppName]);

  useEffect(() => {
    const iconLinks = document.querySelectorAll<HTMLLinkElement>("link[rel*='icon']");
    iconLinks.forEach((link) => {
      link.href = brandingLogo || "/icon.png";
    });
  }, [brandingLogo]);

  return null;
}
