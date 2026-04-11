"use client";
import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { auth, setUserRole, getUserRole } from "@/lib/api";

export function useAuthGuard() {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);
  const [role, setRole] = useState<string | null>(null);

  useEffect(() => {
    const key = localStorage.getItem("observal_api_key");
    if (!key && pathname !== "/login") {
      router.replace("/login");
      return;
    }
    if (!key) {
      setReady(true);
      return;
    }

    const cached = getUserRole();
    if (cached) {
      setRole(cached);
      setReady(true);
      return;
    }

    auth.whoami().then((user) => {
      setUserRole(user.role);
      setRole(user.role);
      setReady(true);
    }).catch(() => {
      router.replace("/login");
    });
  }, [pathname, router]);

  return { ready, role };
}

/**
 * Optional auth — resolves immediately for unauthenticated users.
 * Authenticated users get their role resolved via whoami.
 * Does NOT redirect to login.
 */
export function useOptionalAuth() {
  const [ready, setReady] = useState(false);
  const [role, setRole] = useState<string | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  useEffect(() => {
    const key = localStorage.getItem("observal_api_key");
    if (!key) {
      setReady(true);
      return;
    }

    const cached = getUserRole();
    if (cached) {
      setRole(cached);
      setIsAuthenticated(true);
      setReady(true);
      return;
    }

    auth.whoami().then((user) => {
      setUserRole(user.role);
      setRole(user.role);
      setIsAuthenticated(true);
      setReady(true);
    }).catch(() => {
      // API key invalid — treat as unauthenticated
      setReady(true);
    });
  }, []);

  return { ready, role, isAuthenticated };
}
