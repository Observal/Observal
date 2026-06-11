// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";
import { config } from "./lib/api";
import { initAnalytics, storeFirstTouch } from "./lib/analytics";

// Persist first-touch UTM attribution before any routing strips the query
// string; then initialize product analytics only if the server enables it.
storeFirstTouch();
config
  .public()
  .then((cfg) => initAnalytics(cfg.product_analytics))
  .catch(() => {});

const router = createRouter({
  routeTree,
  defaultPreload: "intent",
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
