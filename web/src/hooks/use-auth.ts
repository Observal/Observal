"use client";
import { useEffect, useState, useSyncExternalStore } from "react";
import { useRouter, usePathname } from "next/navigation";
import { auth, setUserRole, getUserRole, clearSession } from "@/lib/api";

function subscribe(cb: () => void) {
  window.addEventListener("storage", cb);
  return () => window.removeEventListener("storage", cb);
}

function getAuthSnapshot() {
  const key = localStorage.getItem("observal_access_token");
  const role = getUserRole();
  return key ? (role || "pending") : "";
}

function getServerSnapshot() {
  return "";
}

export function useAuthGuard() {
  const router = useRouter();
  const pathname = usePathname();
  const snapshot = useSyncExternalStore(subscribe, getAuthSnapshot, getServerSnapshot);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setHydrated(true);
  }, []);

  const hasToken = snapshot !== "";
  const ready = hasToken && snapshot !== "pending";
  const role = ready ? snapshot : null;

  useEffect(() => {
    if (!hydrated) return;

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
  }, [hydrated, hasToken, snapshot, pathname, router]);

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
