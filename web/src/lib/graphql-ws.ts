// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createClient, type Client } from "graphql-ws";

function getWsUrl(): string {
  const api =
    import.meta.env.VITE_API_URL ||
    (typeof window !== "undefined"
      ? `${window.location.protocol}//${window.location.hostname}:8000`
      : "http://localhost:8000");
  return api.replace(/^http/, "ws") + "/api/v1/graphql";
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem("observal_access_token");
}

let client: Client | null = null;

function getClient(): Client {
  if (!client) {
    client = createClient({
      url: getWsUrl(),
      connectionParams: () => {
        const token = getToken();
        return token ? { authorization: `Bearer ${token}` } : {};
      },
      lazy: true,
      retryAttempts: 5,
    });
  }
  return client;
}

export function subscribeToSessionUpdates(
  onEvent: (sessionId: string, eventName: string) => void,
): () => void {
  return getClient().subscribe(
    {
      query: `subscription SessionUpdated($sessionId: String) {
        sessionUpdated(sessionId: $sessionId) {
          sessionId
          eventName
        }
      }`,
    },
    {
      next: (value) => {
        const data = (value.data as { sessionUpdated?: { sessionId: string; eventName: string } })
          ?.sessionUpdated;
        if (data) {
          onEvent(data.sessionId, data.eventName);
        }
      },
      error: () => {},
      complete: () => {},
    },
  );
}

export function subscribeToReviewUpdates(
  onEvent: (listingId: string, action: string) => void,
): () => void {
  return getClient().subscribe(
    {
      query: `subscription ReviewUpdated($listingId: String) {
        reviewUpdated(listingId: $listingId) {
          listingId
          action
        }
      }`,
    },
    {
      next: (value) => {
        const data = (value.data as { reviewUpdated?: { listingId: string; action: string } })
          ?.reviewUpdated;
        if (data) {
          onEvent(data.listingId, data.action);
        }
      },
      error: () => {},
      complete: () => {},
    },
  );
}
