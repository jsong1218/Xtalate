import { describe, expect, it } from "vitest";
import type { Schemas } from "./client";
import { historyInfiniteQuery } from "./queries";

/**
 * Cursor (keyset) pagination wiring for `GET /v1/history` (slice M33-S2). The page never does offset
 * math: it hands back the server's opaque `next_cursor` verbatim, and stops when the last page omits
 * it. These tests pin that contract on the `infiniteQueryOptions` factory without a network round-trip.
 */
type HistoryResponse = Schemas["HistoryResponse"];

describe("historyInfiniteQuery (Part 6 §4.4, keyset pagination)", () => {
  it("starts from no cursor — the first page asks for the newest rows", () => {
    expect(historyInfiniteQuery().initialPageParam).toBeNull();
  });

  it("advances by the server's opaque next_cursor, never a computed offset", () => {
    const page = { items: [], next_cursor: "opaque-abc" } as HistoryResponse;
    expect(historyInfiniteQuery().getNextPageParam(page, [page], null, [null])).toBe("opaque-abc");
  });

  it("stops paginating when the last page carries no next_cursor", () => {
    const page = { items: [], next_cursor: null } as HistoryResponse;
    expect(
      historyInfiniteQuery().getNextPageParam(page, [page], null, [null]),
    ).toBeUndefined();
  });
});
