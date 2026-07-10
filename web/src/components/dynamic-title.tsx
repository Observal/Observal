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
    // Browsers are very stubborn about updating favicons dynamically.
    // 1. Remove all existing icon tags
    const iconLinks = document.querySelectorAll<HTMLLinkElement>("link[rel*='icon']");
    iconLinks.forEach((link) => link.remove());

    // 2. Extract MIME type if it's a data URI
    let mimeType = "image/png";
    if (brandingLogo && brandingLogo.startsWith("data:")) {
      const match = brandingLogo.match(/^data:([^;]+);/);
      if (match) {
        mimeType = match[1];
      }
    }

    // 3. Create a single fresh icon tag
    const newLink = document.createElement("link");
    newLink.rel = "shortcut icon"; // 'shortcut icon' forces a repaint in older/stubborn browsers
    newLink.type = mimeType;
    newLink.href = brandingLogo || "/icon.png";
    
    document.head.appendChild(newLink);

    // Also add the standard icon rel
    const standardLink = document.createElement("link");
    standardLink.rel = "icon";
    standardLink.type = mimeType;
    standardLink.href = brandingLogo || "/icon.png";
    document.head.appendChild(standardLink);

  }, [brandingLogo]);

  return null;
}
