// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { cn } from "@/lib/utils";
import { registryIdentity, type QualifiedIdentity } from "@/lib/registry-name";

interface RegistryNameProps {
  item: QualifiedIdentity | null | undefined;
  /** Used when the item carries no name at all (e.g. still loading). */
  fallbackName?: string;
  className?: string;
  /** Classes for the name line, so callers keep their own heading sizes. */
  nameClassName?: string;
  handleClassName?: string;
  /** Element for the name line. Defaults to a span so links/headings can wrap it. */
  as?: "span" | "h1" | "h3" | "p";
}

/**
 * Renders a registry identity as the bare name with its owning namespace
 * underneath, e.g. `code-reviewer` over `@alice`.
 *
 * Anything copy-pasted into a shell must keep the canonical `namespace/slug`
 * form instead — see `qualifiedName()` in `@/lib/registry-name`.
 */
export function RegistryName({
  item,
  fallbackName = "",
  className,
  nameClassName,
  handleClassName,
  as: NameTag = "span",
}: RegistryNameProps) {
  const { name, handle } = registryIdentity(item, fallbackName);

  return (
    <span className={cn("block min-w-0", className)}>
      <NameTag className={cn("block truncate", nameClassName)}>{name}</NameTag>
      {handle && (
        <span className={cn("block truncate text-[11px] font-normal text-muted-foreground", handleClassName)}>
          @{handle}
        </span>
      )}
    </span>
  );
}
