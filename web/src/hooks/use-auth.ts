"use client";
import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { auth, setUserRole, getUserRole, clearSession } from "@/lib/api";

function initGuardState(): { ready: boolean; role: string | null } {
  if (typeof window === "undefined") return { ready: false, role: null };
  const key = localStorage.getItem("observal_access_token");
  if (!key) {
    clearSession();
    return { ready: false, role: null };
  }
  const role = getUserRole();
  return { ready: !!role, role };
}

export function useAuthGuard() {
  const router = useRouter();
  const pathname = usePathname();
  const [{ ready, role }, setState] = useState(initGuardState);

  useEffect(() => {
    const key = localStorage.getItem("observal_access_token");
    if (!key) {
      if (pathname !== "/login") {
        router.replace("/login");
      }
      return;
    }

    if (getUserRole()) return;

    auth
      .whoami()
      .then((user) => {
        setUserRole(user.role);
        setState({ ready: true, role: user.role });
      })
      .catch(() => {
        clearSession();
        setState({ ready: false, role: null });
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
    if (!key) return;
    if (getUserRole()) return;

    auth
      .whoami()
      .then((user) => {
        setUserRole(user.role);
        setRole(user.role);
        setIsAuthenticated(true);
        setReady(true);
      })
      .catch(() => {
        clearSession();
        setReady(true);
      });
  }, []);

  return { ready, role, isAuthenticated };
}
