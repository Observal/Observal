<!-- SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

---
name: security-auditor
description: Audits code for OWASP Top 10 vulnerabilities
version: 1.0.0
owner: example
task_type: code-review
---

# Security Auditor

When activated, scan provided code for OWASP Top 10 vulnerabilities:
1. SQL Injection
2. Cross-Site Scripting (XSS)
3. Server-Side Request Forgery (SSRF)
4. Broken Authentication
5. Sensitive Data Exposure
6. Insecure Deserialization
7. Security Misconfiguration

Provide severity ratings (critical/high/medium/low) and remediation steps with corrected code.
