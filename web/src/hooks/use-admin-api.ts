// SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
// SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
// SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
// SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
// SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only


import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";
import {
  auth,
  admin,
  telemetry,
  getUserRole,
} from "@/lib/api";
import { hasMinRole } from "@/hooks/use-role-guard";

// ── Auth ────────────────────────────────────────────────────────────

export function useWhoami() {
  return useQuery({
    queryKey: ["auth", "whoami"],
    queryFn: auth.whoami,
    retry: false,
  });
}

// ── Admin ───────────────────────────────────────────────────────────

export function useAdminUsers() {
  return useQuery({ queryKey: ["admin", "users"], queryFn: admin.users });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: admin.createUser,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success("User created");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to create user");
    },
  });
}

export function useUpdateUserRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; role: string }) =>
      admin.updateRole(vars.id, { role: vars.role }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success("Role updated");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to update role");
    },
  });
}

export function useUpdateUserDepartment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; department: string | null }) =>
      admin.updateDepartment(vars.id, { department: vars.department }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success("Department updated");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to update department");
    },
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => admin.deleteUser(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success("User deleted");
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to delete user");
    },
  });
}

export function useResetPassword() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => admin.resetPassword(id, { generate: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to reset password");
    },
  });
}

export function useAdminSettings() {
  return useQuery({ queryKey: ["admin", "settings"], queryFn: admin.settings });
}

// ── Audit & Security ────────────────────────────────────────────────

export function useAuditLog(filters?: Record<string, string>) {
  return useQuery({
    queryKey: ["admin", "audit-log", filters],
    queryFn: () => admin.auditLog(filters),
  });
}

export function useSecurityEvents(filters?: Record<string, string>) {
  return useQuery({
    queryKey: ["admin", "security-events", filters],
    queryFn: () => admin.securityEvents(filters),
  });
}

export function useDiagnostics() {
  return useQuery({
    queryKey: ["admin", "diagnostics"],
    queryFn: admin.diagnostics,
    refetchInterval: 30_000,
  });
}

export function useSystemWarnings() {
  return useQuery({
    queryKey: ["admin", "system-warnings"],
    queryFn: admin.systemWarnings,
    refetchInterval: 60_000,
  });
}

// ── Retention ────────────────────────────────────────────────────────

export function useRetentionStats() {
  const role = getUserRole();
  return useQuery({
    queryKey: ["admin", "retention", "stats"],
    queryFn: admin.getRetentionStats,
    enabled: hasMinRole(role, "admin"),
  });
}

export function useRetentionWarnings() {
  const role = getUserRole();
  return useQuery({
    queryKey: ["admin", "retention", "warnings"],
    queryFn: admin.getRetentionWarnings,
    enabled: hasMinRole(role, "admin"),
  });
}

// ── Telemetry ───────────────────────────────────────────────────────

export function useTelemetryStatus() {
  return useQuery({
    queryKey: ["telemetry", "status"],
    queryFn: telemetry.status,
  });
}
