// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useEffect } from "react";
import { useDeploymentConfig } from "@/hooks/use-deployment-config";

export function DynamicTitle() {
  const { brandingAppName } = useDeploymentConfig();

  useEffect(() => {
    document.title = brandingAppName || "Observal";
  }, [brandingAppName]);

  return null;
}
