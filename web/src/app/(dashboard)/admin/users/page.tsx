"use client";

import { useState } from "react";
import { useAdminUsers } from "@/hooks/use-api";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { admin } from "@/lib/api";
import { PageHeader } from "@/components/layouts/page-header";
import { DashboardShell, DashboardContent } from "@/components/layouts/dashboard-shell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";

interface User {
  id: string;
  username?: string;
  name?: string;
  email?: string;
  role: string;
  created_at?: string;
}

const ROLES = ["admin", "developer", "user"];

export default function AdminUsersPage() {
  const qc = useQueryClient();
  const { data: users, isLoading } = useAdminUsers();
  const [createOpen, setCreateOpen] = useState(false);
  const [newUser, setNewUser] = useState({ username: "", password: "" });

  const { mutate: changeRole } = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string }) => admin.updateRole(id, { role }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
  });

  const { mutate: createUser, isPending } = useMutation({
    mutationFn: (body: { username: string; password: string }) => admin.createUser(body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin", "users"] }); setCreateOpen(false); setNewUser({ username: "", password: "" }); },
  });

  return (
    <DashboardShell>
      <PageHeader title="Users" breadcrumbs={[{ label: "Dashboard", href: "/" }, { label: "Admin" }, { label: "Users" }]}>
        <Button onClick={() => setCreateOpen(true)}>Create User</Button>
      </PageHeader>
      <DashboardContent>

      {isLoading ? (
        <div className="space-y-2">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(users as User[] | undefined)?.length ? (users as User[]).map((u) => (
              <TableRow key={u.id}>
                <TableCell className="font-medium">{u.username ?? u.name ?? "—"}</TableCell>
                <TableCell>{u.email ?? "—"}</TableCell>
                <TableCell>
                  <Select value={u.role} onValueChange={(role) => changeRole({ id: u.id, role })}>
                    <SelectTrigger className="w-[130px] h-8"><SelectValue /></SelectTrigger>
                    <SelectContent>{ROLES.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
                  </Select>
                </TableCell>
                <TableCell className="text-xs">{u.created_at ? new Date(u.created_at).toLocaleString() : "—"}</TableCell>
              </TableRow>
            )) : (
              <TableRow><TableCell colSpan={4} className="text-center text-muted-foreground">No users</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Create User</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div><Label>Username</Label><Input value={newUser.username} onChange={(e) => setNewUser((p) => ({ ...p, username: e.target.value }))} /></div>
            <div><Label>Password</Label><Input type="password" value={newUser.password} onChange={(e) => setNewUser((p) => ({ ...p, password: e.target.value }))} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button disabled={isPending || !newUser.username || !newUser.password} onClick={() => createUser(newUser)}>Create</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
          </DashboardContent>
    </DashboardShell>
  );
}
