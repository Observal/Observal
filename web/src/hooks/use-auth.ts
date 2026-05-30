// SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useEffect, useSyncExternalStore } from "react";
import { useRouter, useLocation } from "@tanstack/react-router";
import { auth, setUserRole, getUserRole, clearSession, refreshAccessToken } from "@/lib/api";

function subscribe(cb: () => void) {
  window.addEventListener("storage", cb);
  return () => window.removeEventListener("storage", cb);
}

function getAuthSnapshot() {
  if (typeof window === "undefined") return "";
  const key = sessionStorage.getItem("observal_access_token");
  const role = getUserRole();
  if (key) return role || "pending";
  // No access token in sessionStorage, but refresh token may exist (new tab scenario).
  // Mark as "refreshing" so the guard attempts a silent refresh before redirecting.
  const hasRefresh = !!localStorage.getItem("observal_refresh_token");
  return hasRefresh ? "refreshing" : "";
}

function getServerSnapshot() {
  return "ssr";
}

export function useAuthGuard() {
  const router = useRouter();
  const { pathname } = useLocation();
  const snapshot = useSyncExternalStore(subscribe, getAuthSnapshot, getServerSnapshot);
  const isSSR = snapshot === "ssr";
  const hasToken = !isSSR && snapshot !== "" && snapshot !== "refreshing";
  const isRefreshing = snapshot === "refreshing";
  const ready = hasToken && snapshot !== "pending";
  const role = ready ? snapshot : null;

  useEffect(() => {
    if (isSSR) return;

    // New tab: no access token but refresh token exists. Try silent refresh.
    if (isRefreshing) {
      refreshAccessToken().then((ok) => {
        if (ok) {
          // Token restored, trigger whoami to resolve role
          window.dispatchEvent(new Event("storage"));
        } else {
          clearSession();
          window.dispatchEvent(new Event("storage"));
          router.navigate({ to: "/login", replace: true });
        }
      });
      return;
    }

    if (!hasToken && pathname !== "/login") {
      router.navigate({ to: "/login", replace: true });
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
        router.navigate({ to: "/login", replace: true });
      });
    }
  }, [isSSR, hasToken, isRefreshing, snapshot, pathname, router]);

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
