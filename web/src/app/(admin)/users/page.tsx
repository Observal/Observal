"use client";

import { useState, useCallback } from "react";
import { Users, Plus, Copy, Check, Loader2, Key, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useAdminUsers, useCreateUser, useUpdateUserRole, useDeleteUser } from "@/hooks/use-api";
import type { AdminUser } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/components/layouts/page-header";
import { TableSkeleton } from "@/components/shared/skeleton-layouts";
import { ErrorState } from "@/components/shared/error-state";
import { EmptyState } from "@/components/shared/empty-state";
import { ROLE_LABELS, type Role } from "@/hooks/use-role-guard";

const ROLES: Role[] = ["super_admin", "admin", "reviewer", "user"];

function RoleSelect({ userId, currentRole }: { userId: string; currentRole: string }) {
  const mutation = useUpdateUserRole();

  return (
    <Select
      value={currentRole}
      onValueChange={(value) => mutation.mutate({ id: userId, role: value })}
      disabled={mutation.isPending}
    >
      <SelectTrigger className="h-7 w-[140px] text-xs">
        <SelectValue>
          {ROLE_LABELS[currentRole as Role] ?? currentRole}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {ROLES.map((r) => (
          <SelectItem key={r} value={r} className="text-xs">
            {ROLE_LABELS[r]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export default function UsersPage() {
  const { data: users, isLoading, isError, error, refetch } = useAdminUsers();
  const createUser = useCreateUser();
  const deleteUser = useDeleteUser();
  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<string>("user");
  const [createdPassword, setCreatedPassword] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const handleCreate = useCallback(async () => {
    if (!name.trim() || !email.trim()) return;
    createUser.mutate(
      { email: email.trim(), name: name.trim(), role },
      {
        onSuccess: (data) => {
          setCreatedPassword(data.password);
          setName("");
          setEmail("");
          setRole("user");
        },
      },
    );
  }, [name, email, role, createUser]);

  const handleCopyPassword = useCallback(() => {
    if (!createdPassword) return;
    navigator.clipboard.writeText(createdPassword);
    setCopied(true);
    toast.success("Password copied");
    setTimeout(() => setCopied(false), 2000);
  }, [createdPassword]);

  const closeDialog = useCallback(() => {
    setShowCreate(false);
    setCreatedPassword(null);
    setName("");
    setEmail("");
    setRole("user");
  }, []);

  const userCount = (users ?? []).length;

  return (
    <>
      <PageHeader
        title="Users"
        breadcrumbs={[
          { label: "Dashboard", href: "/dashboard" },
          { label: "Users" },
        ]}
        actionButtonsRight={
          <Button size="sm" variant="outline" onClick={() => setShowCreate(true)} className="h-8">
            <Plus className="mr-1 h-3.5 w-3.5" /> Add User
          </Button>
        }
      />
      <div className="p-6 w-full max-w-6xl mx-auto space-y-4">
        {isLoading ? (
          <TableSkeleton rows={5} cols={4} />
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => refetch()} />
        ) : userCount === 0 ? (
          <EmptyState
            icon={Users}
            title="No users yet"
            description="Users will appear here once they sign up or are added by an admin."
          />
        ) : (
          <div className="animate-in space-y-3">
            <p className="text-xs text-muted-foreground">{userCount} user{userCount !== 1 ? "s" : ""}</p>
            <div className="overflow-x-auto rounded-md border border-border">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="h-8 text-xs">Name</TableHead>
                    <TableHead className="h-8 text-xs">Username</TableHead>
                    <TableHead className="h-8 text-xs">Email</TableHead>
                    <TableHead className="h-8 text-xs">Role</TableHead>
                    <TableHead className="h-8 text-xs text-right">Joined</TableHead>
                    <TableHead className="h-8 text-xs w-[60px]" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(users ?? []).map((u: AdminUser) => (
                    <TableRow key={u.id}>
                      <TableCell className="py-1.5">
                        <span className="text-sm font-medium">{u.name ?? "-"}</span>
                      </TableCell>
                      <TableCell className="py-1.5 text-sm text-muted-foreground">
                        {u.username ? `@${u.username}` : "-"}
                      </TableCell>
                      <TableCell className="py-1.5 text-sm text-muted-foreground font-[family-name:var(--font-mono)]">
                        {u.email ?? "-"}
                      </TableCell>
                      <TableCell className="py-1.5">
                        <RoleSelect userId={u.id} currentRole={u.role} />
                      </TableCell>
                      <TableCell className="py-1.5 text-xs text-muted-foreground text-right tabular-nums">
                        {u.created_at ? new Date(u.created_at).toLocaleDateString() : "-"}
                      </TableCell>
                      <TableCell className="py-1.5 text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                          onClick={() => setDeleteTarget(u)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}
      </div>

      {/* Create User Dialog */}
      <Dialog open={showCreate} onOpenChange={(open) => { if (!open) closeDialog(); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{createdPassword ? "User Created" : "Add User"}</DialogTitle>
            <DialogDescription>
              {createdPassword
                ? "Save this password — it will not be shown again."
                : "Create a new user account. They will receive a password for authentication."}
            </DialogDescription>
          </DialogHeader>

          {createdPassword ? (
            <div className="space-y-4">
              <div className="rounded-md border border-border bg-muted/30 p-3">
                <div className="flex items-center gap-2 mb-2">
                  <Key className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Password</span>
                </div>
                <div className="flex items-center gap-2">
                  <code className="text-xs font-[family-name:var(--font-mono)] text-foreground break-all flex-1 select-all">
                    {createdPassword}
                  </code>
                  <Button variant="ghost" size="sm" className="h-7 w-7 p-0 shrink-0" onClick={handleCopyPassword}>
                    {copied ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5" />}
                  </Button>
                </div>
              </div>
              <DialogFooter>
                <Button size="sm" onClick={closeDialog}>Done</Button>
              </DialogFooter>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">Name</label>
                <Input
                  placeholder="Jane Smith"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="h-8 text-sm"
                  autoFocus
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">Email</label>
                <Input
                  type="email"
                  placeholder="jane@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="h-8 text-sm"
                  onKeyDown={(e) => { if (e.key === "Enter") handleCreate(); }}
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-medium text-muted-foreground">Role</label>
                <Select value={role} onValueChange={setRole}>
                  <SelectTrigger className="h-8 text-sm">
                    <SelectValue>
                      {ROLE_LABELS[role as Role] ?? role}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {ROLES.map((r) => (
                      <SelectItem key={r} value={r}>{ROLE_LABELS[r]}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <DialogFooter>
                <Button variant="ghost" size="sm" onClick={closeDialog}>Cancel</Button>
                <Button
                  size="sm"
                  onClick={handleCreate}
                  disabled={createUser.isPending || !name.trim() || !email.trim()}
                >
                  {createUser.isPending ? (
                    <><Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> Creating...</>
                  ) : (
                    "Create User"
                  )}
                </Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Delete User Confirmation Dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete User</DialogTitle>
            <DialogDescription>
              This will permanently delete <strong>{deleteTarget?.name}</strong> ({deleteTarget?.email}) and all associated data.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                if (!deleteTarget) return;
                deleteUser.mutate(deleteTarget.id, {
                  onSuccess: () => setDeleteTarget(null),
                });
              }}
              disabled={deleteUser.isPending}
            >
              {deleteUser.isPending ? (
                <><Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> Deleting...</>
              ) : (
                "Delete User"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
