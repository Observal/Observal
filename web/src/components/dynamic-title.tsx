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
    
    // To force browsers like Chrome and Safari to immediately repaint the favicon,
    // we must create entirely new <link> elements and remove the old ones.
    // Changing the href of an existing tag is often ignored.
    iconLinks.forEach((link) => {
      const newLink = document.createElement("link");
      newLink.rel = link.rel;
      newLink.href = brandingLogo || (link.rel === "alternate icon" ? "/favicon.ico" : "/icon.png");
      
      document.head.appendChild(newLink);
      link.remove();
    });
  }, [brandingLogo]);

  return null;
}
