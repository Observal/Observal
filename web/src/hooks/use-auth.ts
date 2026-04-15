"use client";
import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { auth, setUserRole, getUserRole } from "@/lib/api";

export function useAuthGuard() {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(() => {
    if (typeof window === "undefined") return false;
    const key = localStorage.getItem("observal_access_token");
    if (!key) return false;
    return !!getUserRole();
  });
  const [role, setRole] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return getUserRole();
  });

  useEffect(() => {
    const key = localStorage.getItem("observal_access_token");
    if (!key && pathname !== "/login") {
      router.replace("/login");
      return;
    }
    if (!key) {
      // Already ready from initial state
      return;
    }

    const cached = getUserRole();
    if (cached) {
      // Already ready from initial state
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
  const [ready, setReady] = useState(() => {
    if (typeof window === "undefined") return false;
    const key = localStorage.getItem("observal_access_token");
    if (!key) return true;
    return !!getUserRole();
  });
  const [role, setRole] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return getUserRole();
  });
  const [isAuthenticated, setIsAuthenticated] = useState(() => {
    if (typeof window === "undefined") return false;
    return !!getUserRole();
  });

  useEffect(() => {
    const key = localStorage.getItem("observal_access_token");
    if (!key) {
      // Already ready from initial state
      return;
    }

    const cached = getUserRole();
    if (cached) {
      // Already ready from initial state
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
