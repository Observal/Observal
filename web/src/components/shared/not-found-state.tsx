// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { Link } from "@tanstack/react-router";
import { SearchX } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Full-page state for dead or unauthorized links. Deliberately does not
 * distinguish "does not exist" from "not visible to you" so a shared URL
 * never confirms whether a private object exists.
 */
export function NotFoundState({
  title = "Page not found",
  message = "This link may be broken, private, or the item may have been removed.",
}: {
  title?: string;
  message?: string;
}) {
  return (
    <div className="flex min-h-[60vh] w-full items-center justify-center p-6">
      <div className="w-full max-w-md rounded-lg border bg-card p-8 text-center shadow-sm">
        <SearchX className="mx-auto h-10 w-10 text-muted-foreground" />
        <h1 className="mt-4 text-xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-2 text-sm text-muted-foreground">{message}</p>
        <Button asChild className="mt-6">
          <Link to="/">Back to the registry</Link>
        </Button>
      </div>
    </div>
  );
}
