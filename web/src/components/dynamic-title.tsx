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
    // 1. Remove all existing icon tags
    const iconLinks = document.querySelectorAll<HTMLLinkElement>("link[rel*='icon']");
    iconLinks.forEach((link) => link.remove());

    let finalHref = "/icon.png";
    let mimeType = "image/png";

    if (brandingLogo) {
      if (brandingLogo.startsWith("data:")) {
        // Safari heavily caches and sometimes completely ignores dynamic changes to
        // base64 Data URIs. Converting the Data URI to a Blob URL creates a unique
        // URL for the session, forcing Safari to fetch and repaint the tab icon.
        try {
          const [header, base64] = brandingLogo.split(",");
          const match = header.match(/^data:([^;]+);/);
          if (match) {
            mimeType = match[1];
          }
          const binary = atob(base64);
          const array = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i++) {
            array[i] = binary.charCodeAt(i);
          }
          const blob = new Blob([array], { type: mimeType });
          finalHref = URL.createObjectURL(blob);
        } catch (e) {
          // Fallback if parsing fails
          finalHref = brandingLogo;
        }
      } else {
        // For standard URLs, append a cache-buster timestamp
        try {
          const urlObj = new URL(brandingLogo, window.location.origin);
          urlObj.searchParams.set("t", Date.now().toString());
          finalHref = urlObj.toString();
        } catch (e) {
          finalHref = brandingLogo;
        }
      }
    }

    // 2. Inject fresh tags
    const newLink = document.createElement("link");
    newLink.rel = "shortcut icon";
    newLink.type = mimeType;
    newLink.href = finalHref;
    document.head.appendChild(newLink);

    const standardLink = document.createElement("link");
    standardLink.rel = "icon";
    standardLink.type = mimeType;
    standardLink.href = finalHref;
    document.head.appendChild(standardLink);

    // 3. Cleanup blob URL when logo changes again or unmounts
    return () => {
      if (finalHref.startsWith("blob:")) {
        URL.revokeObjectURL(finalHref);
      }
    };
  }, [brandingLogo]);

  return null;
}
