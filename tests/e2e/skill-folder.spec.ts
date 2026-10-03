// SPDX-FileCopyrightText: 2026 Observal Contributors
// SPDX-FileCopyrightText: 2026 Kaushik <kaushikrjpm10@gmail.com>
// SPDX-License-Identifier: Apache-2.0

/** Browser and HTTP acceptance for the strict skill-folder draft contract. */
import { test, expect } from "@playwright/test";
import { getAccessToken, API_BASE, loginToWebUI } from "./helpers";
import { randomUUID } from "node:crypto";

function skillName(prefix: string) {
	return `${prefix}-${randomUUID().slice(0, 8)}`;
}
function skillMd(name: string) {
	return `---\nname: ${name}\ndescription: Skill folder acceptance example\n---\n\n# Instructions\nRead the linked resources.\n`;
}
async function headers() {
	return { "Content-Type": "application/json", Authorization: `Bearer ${await getAccessToken()}` };
}
async function createDraft(name: string, extra_files: Array<{ path: string; content: string; encoding?: "base64"; executable?: boolean }>) {
	const auth = await headers();
	const response = await fetch(`${API_BASE}/api/v1/skills/folder-drafts`, {
		method: "POST", headers: auth,
		body: JSON.stringify({ name, version: "1.0.0", description: "Skill folder acceptance example",
			owner: "admin", task_type: "general", skill_md_content: skillMd(name), extra_files }),
	});
	return { response, auth };
}
async function removeDraft(listingId: string, auth: Record<string, string>) {
	const response = await fetch(`${API_BASE}/api/v1/skills/${listingId}`, { method: "DELETE", headers: auth });
	expect(response.ok, `Cannot clean up test skill ${listingId}`).toBeTruthy();
}

test("API preserves executable, empty and binary files in a versioned draft", async () => {
	const name = skillName("e2e-folder");
	const { response, auth } = await createDraft(name, [
		{ path: "scripts/run.sh", content: "echo ok\n", executable: true },
		{ path: "templates/empty.txt", content: "" },
		{ path: "assets/icon.bin", content: Buffer.from([0, 255]).toString("base64"), encoding: "base64" },
	]);
	expect(response.status).toBe(200);
	const draft = await response.json();
	expect(draft.listing_id).toBeTruthy();
	expect(draft.version_id).toBeTruthy();
	try {
		const manifestRes = await fetch(`${API_BASE}/api/v1/skills/${draft.listing_id}/versions/${draft.version_id}/manifest`, { headers: auth });
		expect(manifestRes.status).toBe(200);
		const manifest = await manifestRes.json();
		expect(manifest.version_id).toBe(draft.version_id);
		expect(manifest.files.map((file: {path: string}) => file.path)).toEqual(
			expect.arrayContaining(["SKILL.md", "scripts/run.sh", "templates/empty.txt", "assets/icon.bin"])
		);
		expect(manifest.files.find((file: {path: string}) => file.path === "scripts/run.sh").mode).toBe("0755");
		expect(manifest.files.find((file: {path: string}) => file.path === "templates/empty.txt").size).toBe(0);
		const textRes = await fetch(`${API_BASE}/api/v1/skills/${draft.listing_id}/versions/${draft.version_id}/files/scripts/run.sh`, { headers: auth });
		expect(textRes.status).toBe(200);
		expect((await textRes.json()).content).toBe("echo ok\n");
		const binaryRes = await fetch(`${API_BASE}/api/v1/skills/${draft.listing_id}/versions/${draft.version_id}/files/assets/icon.bin`, { headers: auth });
		expect(binaryRes.headers.get("content-type")).toContain("application/octet-stream");
		expect(Buffer.from(await binaryRes.arrayBuffer())).toEqual(Buffer.from([0, 255]));
	} finally {
		await removeDraft(draft.listing_id, auth);
	}
});

test("browser creates a complete draft without submitting it for review", async ({ page }) => {
	const name = skillName("e2e-browser-folder");
	await loginToWebUI(page);
	await page.goto("/components?type=skills");
	await page.getByRole("button", { name: "Create", exact: true }).click();
	const dialog = page.getByRole("dialog");
	await dialog.getByRole("tab", { name: "Upload" }).click();
	await dialog.locator("#skill-file-upload").setInputFiles([
		{ name: "SKILL.md", mimeType: "text/markdown", buffer: Buffer.from(skillMd(name)) },
		{ name: "run.sh", mimeType: "text/plain", buffer: Buffer.from("echo browser\n") },
		{ name: "icon.bin", mimeType: "application/octet-stream", buffer: Buffer.from([0, 255]) },
	]);
	await expect(dialog.locator("#comp-name")).toHaveValue(name);
	await dialog.locator("#comp-version").fill("1.0.0");
	const responsePromise = page.waitForResponse((response) => response.url().endsWith("/api/v1/skills/folder-drafts") && response.request().method() === "POST");
	await dialog.getByRole("button", { name: "Save folder draft" }).click();
	const response = await responsePromise;
	expect(response.status(), await response.text()).toBe(200);
	const draft = await response.json();
	try {
		expect(draft.files.map((file: {path: string}) => file.path)).toEqual(
			expect.arrayContaining(["SKILL.md", "run.sh", "icon.bin"])
		);
		expect(draft.files.find((file: {path: string}) => file.path === "icon.bin").size).toBe(2);
	} finally {
		await removeDraft(draft.listing_id, await headers());
	}
});

test("resource-bearing draft cannot be submitted while delivery gate remains off", async () => {
	test.skip(process.env.OBSERVAL_SKILL_FOLDER_DELIVERY_ENABLED === "true", "Use the gated reviewer flow on the isolated enabled stack");
	const { response, auth } = await createDraft(skillName("e2e-gated-review"), [{ path: "scripts/run.sh", content: "echo gated" }]);
	expect(response.status).toBe(200);
	const draft = await response.json();
	try {
		const submit = await fetch(`${API_BASE}/api/v1/skills/${draft.listing_id}/versions/${draft.version_id}/submit`, {
			method: "POST", headers: auth, body: JSON.stringify({ observed_revision: draft.revision }),
		});
		expect(submit.status).toBe(409);
	} finally {
		await removeDraft(draft.listing_id, auth);
	}
});

test("refuses invalid base64 rather than silently accepting partial bytes", async () => {
	const name = skillName("e2e-invalid-base64");
	const { response } = await createDraft(name, [{ path: "scripts/run.sh", content: "not base64!", encoding: "base64" }]);
	expect([400, 422]).toContain(response.status);
});

test("refuses traversal and excessive file counts", async () => {
	const traversal = await createDraft(skillName("e2e-traversal"), [{ path: "../outside.txt", content: "bad" }]);
	expect([400, 422]).toContain(traversal.response.status);
	const tooMany = await createDraft(skillName("e2e-file-count"),
		Array.from({ length: 129 }, (_, n) => ({ path: `templates/${n}.txt`, content: "" })));
	expect([400, 422]).toContain(tooMany.response.status);
});
