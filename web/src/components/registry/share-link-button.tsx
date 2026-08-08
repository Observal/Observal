// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState } from "react";
import { Check, Link2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { copyToClipboard } from "@/lib/utils";

/**
 * Copies an absolute, canonical shareable URL for the current page object.
 * `path` must be the canonical app path (e.g. `/teamspaces/acme` or
 * `/agents/alice/reviewer`) — the recipient signs in if needed and lands
 * right back on it.
 */
export function ShareLinkButton({ path, label = "Share" }: { path: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const resetTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => () => clearTimeout(resetTimer.current), []);

  async function handleCopy() {
    try {
      await copyToClipboard(window.location.origin + path);
      setCopied(true);
      toast.success("Link copied");
      clearTimeout(resetTimer.current);
      resetTimer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Could not copy the link");
    }
  }

  return (
    <Button variant="outline" size="sm" onClick={handleCopy}>
      {copied ? <Check /> : <Link2 />}
      {label}
    </Button>
  );
}
