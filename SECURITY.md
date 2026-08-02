<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

If you discover a security vulnerability in Observal, please report it responsibly through one of these channels:

1. **GitHub Private Vulnerability Reporting** (preferred): Go to the [Security Advisories](https://github.com/Observal/Observal/security/advisories) page and click "Report a vulnerability".
2. **Email**: Send details to **contact@observal.io**.

### What to Include

- A description of the vulnerability and its potential impact
- Steps to reproduce the issue
- Affected version(s)
- Any suggested fix, if you have one

### What to Expect

- **Acknowledgement** within 48 hours of your report
- **Status update** within 7 days with an initial assessment
- **Resolution target** within 30 days for confirmed vulnerabilities, depending on complexity

We will coordinate disclosure with you. We ask that you give us reasonable time to address the issue before making it public.

## What Qualifies as a Security Issue

Observal handles API keys, authentication tokens, and enterprise telemetry data. The following are examples of issues we consider security-relevant:

- Authentication or authorization bypasses
- API key or token exposure
- SQL injection, command injection, or path traversal
- Cross-site scripting (XSS) or cross-site request forgery (CSRF)
- Server-side request forgery (SSRF)
- Insecure defaults that could expose sensitive data
- Dependency vulnerabilities with a known exploit path

If you're unsure whether something counts, report it anyway. We'd rather triage a false positive than miss a real issue.

## Security Requirements

This section documents what users can and cannot expect in terms of
security from Observal.

### What we guarantee

- API keys are SHA-256 hashed at rest, never stored in plaintext.
- JWTs are signed with ES256 (ECDSA P-256), not HS256. Private keys are
  generated on first run and stored with owner-only permissions.
- Redis fail-closed: if Redis is unavailable, authentication fails rather
  than allowing stale or revoked tokens.
- All outbound network calls go through an SSRF guard.
- Passwords (if password auth is enabled) are stored with per-user salted
  hashes using a key-stretching algorithm.
- Cryptographic keys and nonces are generated using cryptographically secure
  random number generators.
- TLS 1.2+ is supported for all network communications. Insecure protocols
  (HTTP, SSLv3, SSHv1) are not enabled by default.

### What we do not guarantee

- Observal is self-hosted software. The security of the deployment
  environment (network, OS, container runtime) is the operator's
  responsibility.
- Session data in ClickHouse is stored unencrypted at rest. Operators
  should use disk-level encryption if their threat model requires it.
- The web UI does not enforce CSP or HSTS by default. Operators should
  configure these at the reverse proxy or load balancer layer.
- Observal does not provide end-to-end encryption of telemetry data in
  transit between the harness and the server beyond standard HTTPS.

## Recognition

We appreciate responsible disclosure. Contributors who report valid vulnerabilities will be credited in the release notes (unless they prefer to remain anonymous).
