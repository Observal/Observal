// SPDX-FileCopyrightText: 2026 Tanvi Reddy <tanvi.reddy330@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { test, expect } from "@playwright/test";
import { API_BASE, getAccessToken } from "./helpers";

test.describe("Password Change", () => {
  const testEmail = `e2e-pwchange-${Date.now()}@test.example`;
  const originalPassword = "Original@Pass123!";
  const newPassword = "Updated@Secure456!";

  test("change password and login with new credentials", async () => {
    const adminToken = await getAccessToken();
    const adminHeaders = {
      "Content-Type": "application/json",
      Authorization: `Bearer ${adminToken}`,
    };

    // Create a test user with a known password
    const createRes = await fetch(`${API_BASE}/api/v1/admin/users`, {
      method: "POST",
      headers: adminHeaders,
      body: JSON.stringify({
        email: testEmail,
        name: "E2E Password Test",
        role: "user",
        password: originalPassword,
      }),
    });
    expect(createRes.status).toBe(200);

    // Login as the test user to get their token
    const loginRes = await fetch(`${API_BASE}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: testEmail, password: originalPassword }),
    });
    expect(loginRes.status).toBe(200);
    const loginData = await loginRes.json();
    const userToken = loginData.access_token;

    // Change password
    const changeRes = await fetch(`${API_BASE}/api/v1/auth/profile/password`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${userToken}`,
      },
      body: JSON.stringify({
        current_password: originalPassword,
        new_password: newPassword,
      }),
    });
    expect(changeRes.status).toBe(200);
    const changeData = await changeRes.json();
    expect(changeData.message).toBe("Password changed");

    // Login with new password succeeds
    const newLoginRes = await fetch(`${API_BASE}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: testEmail, password: newPassword }),
    });
    expect(newLoginRes.status).toBe(200);

    // Login with old password fails
    const oldLoginRes = await fetch(`${API_BASE}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: testEmail, password: originalPassword }),
    });
    expect(oldLoginRes.status).toBe(401);
  });
});
