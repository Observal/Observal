// SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

"use client";
import { useEffect, useSyncExternalStore } from "react";
import { useRouter, usePathname } from "next/navigation";
import { auth, setUserRole, getUserRole, clearSession } from "@/lib/api";

function subscribe(cb: () => void) {
  window.addEventListener("storage", cb);
  return () => window.removeEventListener("storage", cb);
}

function getAuthSnapshot() {
  if (typeof window === "undefined") return "";
  const key = sessionStorage.getItem("observal_access_token");
  const role = getUserRole();
  return key ? (role || "pending") : "";
}

function getServerSnapshot() {
  return "ssr";
}

export function useAuthGuard() {
  const router = useRouter();
  const pathname = usePathname();
  const snapshot = useSyncExternalStore(subscribe, getAuthSnapshot, getServerSnapshot);
  const isSSR = snapshot === "ssr";
  const hasToken = !isSSR && snapshot !== "";
  const ready = hasToken && snapshot !== "pending";
  const role = ready ? snapshot : null;

  useEffect(() => {
    if (isSSR) return;

    if (!hasToken && pathname !== "/login") {
      router.replace("/login");
      return;
    }
    if (!hasToken) return;

    if (snapshot === "pending") {
      auth.whoami().then((user) => {
        setUserRole(user.role);
        window.dispatchEvent(new Event("storage"));
      }).catch(() => {
        clearSession();
        window.dispatchEvent(new Event("storage"));
        router.replace("/login");
      });
    }
  }, [isSSR, hasToken, snapshot, pathname, router]);

  return { ready, role };
}

/**
 * Optional auth — resolves immediately for unauthenticated users.
 * Authenticated users get their role resolved via whoami.
 * Does NOT redirect to login.
 */
export function useOptionalAuth() {
  const snapshot = useSyncExternalStore(subscribe, getAuthSnapshot, getServerSnapshot);
  const hasToken = snapshot !== "";
  const ready = !hasToken || snapshot !== "pending";
  const role = (hasToken && snapshot !== "pending") ? snapshot : null;
  const isAuthenticated = hasToken && snapshot !== "pending";

  useEffect(() => {
    if (hasToken && snapshot === "pending") {
      auth.whoami().then((user) => {
        setUserRole(user.role);
        window.dispatchEvent(new Event("storage"));
      }).catch(() => {
        clearSession();
        window.dispatchEvent(new Event("storage"));
      });
    }
  }, [hasToken, snapshot]);

  return { ready, role, isAuthenticated };
}
