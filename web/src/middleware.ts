// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

/**
 * Next.js edge middleware — injects security headers on every response.
 *
 * Content-Security-Policy prevents XSS by restricting where scripts,
 * styles, and other resources can be loaded from.
 *
 * X-Frame-Options and frame-ancestors together prevent clickjacking.
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'", // unsafe-inline required for Next.js hydration scripts
  "style-src 'self' 'unsafe-inline'", // unsafe-inline needed for Tailwind/shadcn
  "img-src 'self' data: https:",
  "font-src 'self'",
  "connect-src 'self' https:",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

export function middleware(_request: NextRequest) {
  const response = NextResponse.next();
  response.headers.set("Content-Security-Policy", CSP);
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("X-Content-Type-Options", "nosniff");
  return response;
}

export const config = {
  // Apply to all routes except Next.js internals and static assets
  matcher: "/((?!_next/static|_next/image|favicon.ico).*)",
};
