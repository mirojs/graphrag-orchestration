import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { groupHistory } from "../components/HistoryPanel/HistoryPanel";
import type { HistoryData } from "../components/HistoryItem";

// Fix "now" to 2026-03-02 12:00:00 UTC for deterministic tests
const NOW = new Date("2026-03-02T12:00:00Z");

function makeItem(id: string, date: Date): HistoryData {
    return { id, title: `Chat ${id}`, timestamp: date.getTime() };
}

describe("groupHistory", () => {
    beforeEach(() => {
        vi.useFakeTimers();
        vi.setSystemTime(NOW);
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it("returns empty object for empty input", () => {
        expect(groupHistory([])).toEqual({});
    });

    it("groups today's items", () => {
        const todayItem = makeItem("1", new Date("2026-03-02T08:00:00Z"));
        const groups = groupHistory([todayItem]);
        expect(groups["history.today"]).toHaveLength(1);
    });

    it("groups yesterday's items", () => {
        const yesterdayItem = makeItem("1", new Date("2026-03-01T15:00:00Z"));
        const groups = groupHistory([yesterdayItem]);
        expect(groups["history.yesterday"]).toHaveLength(1);
    });

    it("groups last 7 days items", () => {
        const item = makeItem("1", new Date("2026-02-25T10:00:00Z"));
        const groups = groupHistory([item]);
        expect(groups["history.last7days"]).toHaveLength(1);
    });

    it("groups last 30 days items", () => {
        const item = makeItem("1", new Date("2026-02-05T10:00:00Z"));
        const groups = groupHistory([item]);
        expect(groups["history.last30days"]).toHaveLength(1);
    });

    it("groups older items by month/year", () => {
        const item = makeItem("1", new Date("2025-11-15T10:00:00Z"));
        const groups = groupHistory([item]);
        const keys = Object.keys(groups);
        // Should not be in any of the recent buckets
        expect(groups["history.today"]).toBeUndefined();
        expect(groups["history.yesterday"]).toBeUndefined();
        expect(groups["history.last7days"]).toBeUndefined();
        expect(groups["history.last30days"]).toBeUndefined();
        // Should have exactly one group with a month/year label
        expect(keys).toHaveLength(1);
        expect(keys[0]).toContain("2025");
    });

    it("distributes mixed items into correct groups", () => {
        const items = [
            makeItem("today", new Date("2026-03-02T09:00:00Z")),
            makeItem("yesterday", new Date("2026-03-01T09:00:00Z")),
            makeItem("lastweek", new Date("2026-02-24T09:00:00Z")),
            makeItem("old", new Date("2025-06-01T09:00:00Z"))
        ];
        const groups = groupHistory(items);
        expect(groups["history.today"]).toHaveLength(1);
        expect(groups["history.yesterday"]).toHaveLength(1);
        expect(groups["history.last7days"]).toHaveLength(1);
        // The old item should be in a month-year bucket
        const monthKeys = Object.keys(groups).filter(k => !k.startsWith("history."));
        expect(monthKeys).toHaveLength(1);
    });
});
