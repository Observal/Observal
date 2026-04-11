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
