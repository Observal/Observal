// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Ban, Copy, Link2, Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import { admin } from "@/lib/api";
import type { AdminInvite, AdminInviteCreated } from "@/lib/types";
import { copyToClipboard } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const STATE_STYLES: Record<AdminInvite["state"], string> = {
  active: "border-success/40 text-success",
  expired: "text-muted-foreground",
  revoked: "border-destructive/40 text-destructive",
  exhausted: "text-muted-foreground",
};

/**
 * Admin-minted invite links. An invite authorizes account creation only —
 * never membership or an elevated role — and its plaintext URL is shown
 * exactly once here, at mint time. Requires the auth.invite_links_enabled
 * setting; the create call answers 403 with a pointer when it is off.
 */
export function InviteLinksCard() {
  const qc = useQueryClient();
  const invitesQuery = useQuery({ queryKey: ["admin", "invites"], queryFn: admin.invites });
  const [createOpen, setCreateOpen] = useState(false);
  const [expiresDays, setExpiresDays] = useState("7");
  const [maxUses, setMaxUses] = useState("");
  const [nextPath, setNextPath] = useState("");
  const [minted, setMinted] = useState<AdminInviteCreated | null>(null);

  const createInvite = useMutation({
    mutationFn: admin.createInvite,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["admin", "invites"] });
      setCreateOpen(false);
      setMinted(data);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create the invite"),
  });
  const revokeInvite = useMutation({
    mutationFn: admin.revokeInvite,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "invites"] });
      toast.success("Invite revoked");
    },
    onError: (err: Error) => toast.error(err.message || "Failed to revoke the invite"),
  });

  const invites = invitesQuery.data ?? [];

  async function copyMinted() {
    if (!minted) return;
    try {
      await copyToClipboard(minted.url);
      toast.success("Invite link copied");
    } catch {
      toast.error("Could not copy the link");
    }
  }

  return (
    <div className="rounded-lg border border-border/80 bg-card/70 p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Link2 className="h-4 w-4 text-primary-accent" />
          <div>
            <h3 className="text-sm font-medium">Invite links</h3>
            <p className="text-xs text-muted-foreground">
              Let someone create an account while self-registration stays off. The link never grants
              membership or elevated roles.
            </p>
          </div>
        </div>
        <Button size="sm" variant="outline" className="h-8" onClick={() => setCreateOpen(true)}>
          <Plus className="mr-1 h-3.5 w-3.5" /> New invite
        </Button>
      </div>

      {invitesQuery.isLoading ? (
        <div className="h-10 animate-pulse rounded-md bg-muted/60" />
      ) : invites.length === 0 ? (
        <p className="py-2 text-xs text-muted-foreground">
          No invites yet. Minting one requires the <code className="font-mono">auth.invite_links_enabled</code>{" "}
          setting.
        </p>
      ) : (
        <div className="divide-y divide-border/70 rounded-md border border-border/80">
          {invites.map((invite) => (
            <div key={invite.id} className="flex items-center justify-between gap-3 px-3 py-2 text-xs">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <Badge variant="outline" className={`px-1.5 py-0 text-[10px] capitalize ${STATE_STYLES[invite.state]}`}>
                  {invite.state}
                </Badge>
                <span className="text-muted-foreground">
                  {invite.use_count}
                  {invite.max_uses != null ? ` / ${invite.max_uses}` : ""} used
                </span>
                <span className="text-muted-foreground">
                  expires {new Date(invite.expires_at).toLocaleDateString()}
                </span>
                {invite.next_path && (
                  <span className="truncate font-mono text-muted-foreground">→ {invite.next_path}</span>
                )}
                {invite.invited_by_username && (
                  <span className="text-muted-foreground">by @{invite.invited_by_username}</span>
                )}
              </div>
              {invite.state === "active" && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 shrink-0 px-2 text-muted-foreground hover:text-destructive"
                  onClick={() => revokeInvite.mutate(invite.id)}
                  disabled={revokeInvite.isPending}
                >
                  <Ban className="mr-1 h-3 w-3" /> Revoke
                </Button>
              )}
            </div>
          ))}
        </div>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New invite link</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="invite-expiry">Expires in (days)</Label>
              <Input
                id="invite-expiry"
                type="number"
                min={1}
                max={365}
                value={expiresDays}
                onChange={(e) => setExpiresDays(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="invite-max-uses">Max uses (empty = unlimited)</Label>
              <Input
                id="invite-max-uses"
                type="number"
                min={1}
                value={maxUses}
                onChange={(e) => setMaxUses(e.target.value)}
                placeholder="Unlimited"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="invite-next">Destination after sign-up (optional)</Label>
              <Input
                id="invite-next"
                value={nextPath}
                onChange={(e) => setNextPath(e.target.value)}
                placeholder="/teamspaces/acme"
              />
              <p className="text-xs text-muted-foreground">
                A relative path the new user lands on, e.g. a teamspace page where they can request to
                join.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={createInvite.isPending}
              onClick={() =>
                createInvite.mutate({
                  expires_in_days: Math.max(1, Math.min(365, Number(expiresDays) || 7)),
                  max_uses: maxUses.trim() ? Math.max(1, Number(maxUses)) : null,
                  next_path: nextPath.trim() || undefined,
                })
              }
            >
              {createInvite.isPending ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : null}
              Create invite
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={!!minted}
        onOpenChange={(open) => {
          if (!open) setMinted(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Invite link created</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <code className="block break-all rounded-md border border-border/80 bg-background px-3 py-2 font-mono text-xs">
              {minted?.url}
            </code>
            <p className="text-xs text-muted-foreground">
              Copy it now — this link is shown only once and cannot be recovered later.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setMinted(null)}>
              Done
            </Button>
            <Button onClick={copyMinted}>
              <Copy className="mr-1.5 h-3.5 w-3.5" /> Copy link
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
