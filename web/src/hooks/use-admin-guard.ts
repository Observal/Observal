"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getUserRole } from "@/lib/api";

export function useAdminGuard() {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const role = getUserRole();
    if (role !== "admin") {
      router.replace("/");
      return;
    }
    setReady(true);
  }, [router]);

  return ready;
}
