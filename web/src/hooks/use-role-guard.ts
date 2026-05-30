// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import { useEffect, useSyncExternalStore } from "react";
import { useRouter } from "@tanstack/react-router";
import { toast } from "sonner";
import { getUserRole } from "@/lib/api";

/** Canonical role type matching the backend 4-tier RBAC. */
export type Role = "super_admin" | "admin" | "reviewer" | "user";

/** Ordered from most to least privileged. */
const ROLE_HIERARCHY: Role[] = ["super_admin", "admin", "reviewer", "user"];

/** Display labels for UI rendering. */
export const ROLE_LABELS: Record<Role, string> = {
  super_admin: "Super Admin",
  admin: "Admin",
  reviewer: "Reviewer",
  user: "Viewer",
};

/** Returns true if `userRole` is at or above `minRole` in the hierarchy. */
export function hasMinRole(userRole: string | null, minRole: Role): boolean {
  if (!userRole) return false;
  const userIdx = ROLE_HIERARCHY.indexOf(userRole as Role);
  const minIdx = ROLE_HIERARCHY.indexOf(minRole);
  if (userIdx === -1) return false;
  return userIdx <= minIdx;
}

function subscribe(cb: () => void) {
  window.addEventListener("storage", cb);
  return () => window.removeEventListener("storage", cb);
}

function getRoleSnapshot() {
  if (typeof window === "undefined") return "";
  return getUserRole() || "";
}

function getServerSnapshot() {
  return "ssr";
}

/**
 * Guard hook that checks if the current user meets a minimum role.
 * Redirects to "/" if the role is insufficient.
 */
export function useRoleGuard(minRole: Role) {
  const router = useRouter();
  const role = useSyncExternalStore(subscribe, getRoleSnapshot, getServerSnapshot);
  const isSSR = role === "ssr";
  const ready = !isSSR && role !== "" && hasMinRole(role, minRole);

  useEffect(() => {
    if (isSSR) return;
    if (role !== "" && !hasMinRole(role, minRole)) {
      toast.error("You do not have permission to access this page.");
      router.navigate({ to: "/", replace: true });
    }
  }, [isSSR, role, minRole, router]);

  return { ready };
}
