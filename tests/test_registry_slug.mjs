// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import assert from "node:assert/strict";
import test from "node:test";
import { isValidAgentName, normalizeAgentName, slugifyRegistryText } from "../web/src/lib/registry-name.ts";

test("replaces spaces with a single hyphen while typing", () => {
	assert.equal(slugifyRegistryText("Cloud ", { preserveTrailingSeparator: true }), "cloud-");
	assert.equal(slugifyRegistryText("Cloud  Computing", { preserveTrailingSeparator: true }), "cloud-computing");
	assert.equal(slugifyRegistryText("Cloud  Computing"), "cloud-computing");
});

test("trims separators after the length limit", () => {
	assert.equal(slugifyRegistryText(`${"a".repeat(31)} `, { maxLength: 32 }), "a".repeat(31));
});

test("preserves underscores for agent names when requested", () => {
	assert.equal(slugifyRegistryText("Cloud_Tools", { allowUnderscore: true }), "cloud_tools");
});

test("uses hyphens for team handle input", () => {
	assert.equal(slugifyRegistryText("Cloud_Tools"), "cloud-tools");
});

test("rejects names that normalize to an empty draft name", () => {
	assert.equal(normalizeAgentName("!!!"), "");
	assert.equal(isValidAgentName("!!!"), false);
	assert.equal(isValidAgentName("Cloud Computing"), true);
});
