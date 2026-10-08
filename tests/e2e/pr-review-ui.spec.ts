// SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { expect, test } from "@playwright/test";

const id = "e2d6c522-969d-4725-81ab-ed87c17af09c";
const now = new Date().toISOString();
const summary = (number: number, title: string, subject_type: "agent" | "skill", depends_on: number[] = []) => ({
  id: `${number}0000000-0000-4000-8000-000000000000`, number, title, subject_type, subject_id: id,
  version: "1.0.0", team_id: null, state: "open", author_id: id, head_revision: 1, updated_at: now,
  gate: { ready: false, approvals: 0, required: 2, policy_source: "organization", requirements: [] },
  threads: { total: 1, unresolved: 1 }, checks: { pass: 2, fail: 0, warn: 1, skipped: 0 },
  depends_on, requested_from_me: true, my_last_submission: null,
});

test("review queue shows pinned dependencies in the Observal shell", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => {
    sessionStorage.setItem("observal_access_token", "review-ui-test");
    localStorage.setItem("observal_user_role", "reviewer");
  });
  await page.route("**/api/v1/**", route => route.fulfill({ json: { items: [], unread: 0, action_required: 0, by_kind: {}, by_subject_type: {} } }));
  await page.route("**/api/v1/auth/whoami", route => route.fulfill({ json: { id, username: "reviewer", name: "Review Tester", role: "reviewer" } }));
  await page.route("**/api/v1/reviews?*", route => route.fulfill({ json: {
    items: [summary(42, "Agent: repository assistant", "agent", [43]), summary(43, "Skill: verify source", "skill")],
    total: 2, limit: 100, offset: 0,
  } }));
  await page.goto("/review");
  await expect(page.getByRole("heading", { name: "Review", exact: true })).toBeVisible();
  await expect(page.getByText("Agent: repository assistant")).toBeVisible();
  await expect(page.getByText("Skill: verify source")).toBeVisible();
  await expect(page.getByText("Waits on #43")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("pr-review-queue-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByText("Skill: verify source")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("pr-review-queue-mobile.png"), fullPage: true });
});

test("review detail exposes the gate, revision diff, and a separate verdict", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => {
    sessionStorage.setItem("observal_access_token", "review-ui-test");
    localStorage.setItem("observal_user_role", "reviewer");
  });
  const detail = {
    ...summary(42, "Skill: verify source", "skill"), body: "Check the **permission boundary** before publishing.",
    opened_at: now, closed_at: null, closed_reason: null, published_at: null, published_by: null,
    base_version_id: null, head_revision_id: id, my_subscription: null, self_approval_allowed: false,
    revisions: [{ id, number: 1, message: "Initial release", created_by: id, created_at: now, pruned: false }],
    requested_reviewers: [id],
  };
  const diff = [{ path: "SKILL.md", status: "added", lang: "markdown", pinned: false, generated: false,
    additions: 1, deletions: 0, too_large: false,
    hunks: [{ base_start: 0, base_lines: 0, head_start: 1, head_lines: 1, lines: [{ t: "add", h: 1, s: "# Verify source" }] }],
  }];
  const verdicts: unknown[] = [];
  await page.route("**/api/v1/**", route => route.fulfill({ json: { items: [], unread: 0, action_required: 0 } }));
  await page.route("**/api/v1/auth/whoami", route => route.fulfill({ json: { id: "other-reviewer", username: "reviewer", name: "Review Tester", role: "reviewer" } }));
  await page.route("**/api/v1/reviews/42**", route => {
    const url = new URL(route.request().url());
    const suffix = url.pathname.replace("/api/v1/reviews/42", "");
    if (suffix === "/submissions" && route.request().method() === "POST") {
      verdicts.push(route.request().postDataJSON());
      return route.fulfill({ json: { state: "approved" } });
    }
    const value = suffix === "/gate" ? detail.gate : suffix === "/timeline" ? { items: [], next_cursor: null }
      : suffix === "/threads" || suffix === "/checks" ? [] : suffix === "/diff" ? diff : detail;
    return route.fulfill({ json: value });
  });
  await page.goto("/review/42");
  await expect(page.getByRole("heading", { name: "Skill: verify source" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Publication gate" })).toBeVisible();
  await page.getByRole("button", { name: "Files changed" }).click();
  await expect(page.getByRole("table", { name: "Diff for SKILL.md" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("pr-review-detail-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: "Review changes" }).click();
  await page.getByRole("radio", { name: "Approve" }).check();
  await page.getByRole("button", { name: "Submit review" }).click();
  await expect.poll(() => verdicts.length).toBe(1);
  expect(verdicts[0]).toEqual({ verdict: "approve", body: "" });
});
