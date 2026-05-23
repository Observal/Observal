// SPDX-FileCopyrightText: 2026 Tanvi Reddy <tanvi.reddy330@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { API_BASE, getAccessToken, loginToWebUI } from "./helpers";

/** Create a test agent and return its ID */
async function createTestAgent(token: string): Promise<string> {
  const res = await fetch(`${API_BASE}/api/v1/agents`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      name: `e2e-feedback-agent-${Date.now()}`,
      version: "1.0.0",
      description: "Agent for feedback e2e test",
      owner: "admin",
      model_name: "claude-sonnet-4-20250514",
      goal_template: {
        description: "Feedback test",
        sections: [{ name: "Goal", content: "Test feedback" }],
      },
    }),
  });
  expect(res.status).toBe(200);
  const agent = await res.json();
  return agent.id;
}

test.describe("Feedback - Star rating and comment", () => {
  test("leave star rating with comment and verify it appears", async () => {
    const adminToken = await getAccessToken();
    const agentId = await createTestAgent(adminToken);

    try {
      // Submit a 5-star rating with comment
      const feedbackRes = await fetch(`${API_BASE}/api/v1/feedback`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${adminToken}`,
        },
        body: JSON.stringify({
          listing_id: agentId,
          listing_type: "agent",
          rating: 5,
          comment: "Excellent agent, works perfectly!",
        }),
      });
      expect(feedbackRes.status).toBe(200);
      const feedback = await feedbackRes.json();
      expect(feedback.rating).toBe(5);
      expect(feedback.comment).toBe("Excellent agent, works perfectly!");

      // Verify it appears in the feedback list
      const listRes = await fetch(`${API_BASE}/api/v1/feedback/agent/${agentId}`, {
        headers: { Authorization: `Bearer ${adminToken}` },
      });
      expect(listRes.status).toBe(200);
      const feedbackList = await listRes.json();
      expect(feedbackList.length).toBeGreaterThanOrEqual(1);
      expect(feedbackList[0].rating).toBe(5);
    } finally {
      await fetch(`${API_BASE}/api/v1/agents/${agentId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${adminToken}` },
      }).catch(() => {});
    }
  });
});

test.describe("Feedback - Multiple users aggregate", () => {
  test("two users rate and average is calculated correctly", async () => {
    const adminToken = await getAccessToken();
    const agentId = await createTestAgent(adminToken);
    let user2Id: string | null = null;

    try {
      // Admin rates 4 stars
      const fb1Res = await fetch(`${API_BASE}/api/v1/feedback`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${adminToken}`,
        },
        body: JSON.stringify({ listing_id: agentId, listing_type: "agent", rating: 4 }),
      });
      expect(fb1Res.status).toBe(200);

      // Create a second user
      const ts = Date.now();
      const user2Email = `e2e-fb2-${ts}@test.example`;
      const user2Pass = "TestPass@12345!";
      const createUserRes = await fetch(`${API_BASE}/api/v1/admin/users`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${adminToken}`,
        },
        body: JSON.stringify({ email: user2Email, name: "E2E User 2", role: "user", password: user2Pass }),
      });
      expect(createUserRes.status).toBe(200);
      const createdUser = await createUserRes.json();
      user2Id = createdUser.id;

      // Login as user 2
      const user2LoginRes = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: user2Email, password: user2Pass }),
      });
      expect(user2LoginRes.status).toBe(200);
      const { access_token: user2Token } = await user2LoginRes.json();

      // User 2 rates 2 stars
      const fb2Res = await fetch(`${API_BASE}/api/v1/feedback`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${user2Token}`,
        },
        body: JSON.stringify({ listing_id: agentId, listing_type: "agent", rating: 2 }),
      });
      expect(fb2Res.status).toBe(200);

      // Get feedback summary — average should be 3.0
      // Note: this endpoint is intentionally called without auth to test public access
      const summaryRes = await fetch(`${API_BASE}/api/v1/feedback/summary/${agentId}`);
      expect(summaryRes.status).toBe(200);
      const summary = await summaryRes.json();
      expect(summary.average_rating).toBeCloseTo(3.0, 1);
      expect(summary.total_reviews).toBe(2);
    } finally {
      // Cleanup agent
      await fetch(`${API_BASE}/api/v1/agents/${agentId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${adminToken}` },
      }).catch(() => {});
      // Cleanup user2
      if (user2Id) {
        await fetch(`${API_BASE}/api/v1/admin/users/${user2Id}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${adminToken}` },
        }).catch(() => {});
      }
    }
  });
});

test.describe("Feedback - Aggregate on agent card", () => {
  test("star rating displays on agents list page", async ({ page }) => {
    const adminToken = await getAccessToken();
    const agentId = await createTestAgent(adminToken);

    try {
      // Submit a rating so the agent has a score
      await fetch(`${API_BASE}/api/v1/feedback`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${adminToken}`,
        },
        body: JSON.stringify({ listing_id: agentId, listing_type: "agent", rating: 4 }),
      });

      // Login to web UI and navigate to agents page
      await loginToWebUI(page);
      await page.goto("/agents");

      // Wait for the page content to load (avoid deprecated networkidle)
      await page.waitForSelector("table, [data-testid='agents-list']", { timeout: 10_000 }).catch(() => {});
      await page.waitForTimeout(1000);

      // Verify star ratings or numeric ratings are displayed on the page
      // Scoped to table/list area to avoid matching unrelated numbers
      const contentArea = page.locator("main");
      const starElement = contentArea.locator('[aria-label*="rating"], [data-testid*="rating"]').first();
      const ratingText = contentArea.locator('text=/\\d\\.\\d/').first();

      const hasStars = await starElement.isVisible().catch(() => false);
      const hasRatingText = await ratingText.isVisible().catch(() => false);

      // At least one rating indicator should be visible (stars or numeric)
      expect(hasStars || hasRatingText).toBe(true);
    } finally {
      await fetch(`${API_BASE}/api/v1/agents/${agentId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${adminToken}` },
      }).catch(() => {});
    }
  });
});
