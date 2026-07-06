<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# AI Policy

Observal welcomes the use of AI coding tools. They can meaningfully accelerate development and help contributors tackle complex changes. At the same time, we have zero tolerance for **slop**: unreviewed, low-effort output that wastes reviewer time and degrades the codebase.

This policy tells you what is expected when AI tools are part of your workflow.

> [!NOTE]
> This policy was informed by the [AnkiDroid AI Policy](https://github.com/ankidroid/Anki-Android/blob/main/AI_POLICY.md), adapted with a more permissive stance that reflects the nature of an AI-native project. Attribution is given with thanks.

---

## Autonomous coding agents are not permitted

**Tools like Devin, SWE-agent, OpenHands, and similar autonomous agents that write and submit code without meaningful human authorship are not allowed to contribute to this project.**

This is not a quality judgement, it is a legal one.

The [US Copyright Office's January 2025 report on AI copyrightability](https://www.copyright.gov/ai/Copyright-and-Artificial-Intelligence-Part-2-Copyrightability-Report.pdf) explicitly confirms that purely AI-generated code, where the AI made all material creative choices in response to a task description, has **no copyright owner**. Not you, not the AI company.

This creates three structural problems for this project:

1. **The CLA is invalidated.** Our CLA requires you to assert that the contribution is your original creation and that you have the right to license it. You cannot make that assertion for code an autonomous agent wrote.

2. **The license chain breaks.** Apache-2.0 is a copyright license. It works by a copyright holder granting rights. If a contribution has no copyright owner, the license cannot cover it, creating a licensing hole in the codebase that cannot be retroactively fixed.

3. **Training data provenance is unknowable.** Autonomous agents may reproduce verbatim or substantially similar GPL-licensed code from their training data without attribution, a risk confirmed by active litigation (_Doe 1 v. GitHub, Inc._, N.D. Cal. 2022) and studied by the [Software Freedom Conservancy](https://sfconservancy.org/blog/2022/feb/03/github-copilot-copyleft-gpl/) and [FSF](https://www.fsf.org/news/publication-of-the-fsf-funded-white-papers-on-questions-around-copilot).

This is the same position taken by [curl](https://curl.se/dev/contribute.html) and documented by the FSF and SFC. **Any PR identified as having been submitted by an autonomous agent will be closed immediately.**

> [!NOTE]
> Using AI tools as a _coding assistant_, where you write, review, and are accountable for the code, is explicitly welcome. The distinction is human authorship and accountability, not whether AI was involved.

---

## What is allowed

- Using AI tools (Copilot, Cursor, Claude, etc.) to write, refactor, or review code, provided you review and own the result
- Using AI tools to help understand the codebase, generate test cases, or draft documentation
- Submitting AI-assisted contributions, provided all requirements below are met

---

## Requirements for AI-assisted contributions

### You must be able to explain every line

If a reviewer asks you to explain a change, you must be able to do so clearly and accurately. "The AI wrote it" is not an acceptable answer. If you cannot explain it, do not submit it.

### It must compile and the tests must pass

Run `make test` and verify CI passes before opening a PR. Do not submit code you have not executed locally.

### Read through the full diff yourself

Before opening a PR, read every line of your diff. AI tools make confident-looking mistakes. You are responsible for catching them.

### Frontend changes require screenshots

If your PR touches the web frontend, attach screenshots of all affected screens to the PR body. This is required regardless of whether the change was AI-assisted.

### Label AI use and include the tool version

If AI tools made a nontrivial contribution to your PR, state so in the PR description. Include the tool name and version (for example: `Claude Sonnet 4`, `GPT-4o`, `Cursor 0.48`). A nontrivial contribution means the AI wrote, restructured, or significantly modified the code, not just autocomplete suggestions.

---

## What is not allowed

- Autonomous coding agents submitting PRs (see above)
- Using AI tools to write GitHub comments, including filling in the PR template
- Submitting output you have not read and understood
- Repeating the same AI-generated mistakes across multiple PRs after being told about them

> [!WARNING]
> PRs that show clear signs of unreviewed AI output, boilerplate that does not match the codebase, incorrect variable names, placeholder text, hallucinated API calls, will be **closed without review**. A second instance may result in a contribution ban.
