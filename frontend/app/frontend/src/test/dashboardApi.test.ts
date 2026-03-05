import { describe, it, expect, vi, beforeEach } from "vitest";
import {
    fetchUserProfile,
    fetchUsageStats,
    fetchSystemMetrics,
    fetchPlanInfo
} from "../api/dashboard";

vi.mock("../api/api", () => ({
    getHeaders: vi.fn(async () => ({ Authorization: "Bearer test-token" })),
    fetchWithAuthRetry: vi.fn((url: string, init: RequestInit) => globalThis.fetch(url, init))
}));

function mockFetchOnce(body: unknown, status = 200) {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(JSON.stringify(body), { status, statusText: status === 200 ? "OK" : "Error" })
    );
}

function mockFetchError(status: number, statusText: string) {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(null, { status, statusText })
    );
}

beforeEach(() => {
    vi.restoreAllMocks();
});

describe("fetchUserProfile", () => {
    it("fetches /dashboard/me", async () => {
        const profile = { user_id: "u1", display_name: "Test", is_admin: false, plan: "free" };
        mockFetchOnce(profile);
        const result = await fetchUserProfile("token");
        expect(result.user_id).toBe("u1");
        expect(globalThis.fetch).toHaveBeenCalledWith("/dashboard/me", expect.any(Object));
    });

    it("throws on error", async () => {
        mockFetchError(401, "Unauthorized");
        await expect(fetchUserProfile("token")).rejects.toThrow("Failed to fetch profile: 401");
    });
});

describe("fetchUsageStats", () => {
    it("fetches /dashboard/me/usage", async () => {
        const usage = { queries_today: 5, queries_this_month: 100 };
        mockFetchOnce(usage);
        const result = await fetchUsageStats("token");
        expect(result.queries_today).toBe(5);
    });
});

describe("fetchSystemMetrics", () => {
    it("fetches /dashboard/admin/metrics", async () => {
        const metrics = { total_users: 42, error_rate: 0.01 };
        mockFetchOnce(metrics);
        const result = await fetchSystemMetrics("token");
        expect(result.total_users).toBe(42);
    });

    it("throws on 403", async () => {
        mockFetchError(403, "Forbidden");
        await expect(fetchSystemMetrics("token")).rejects.toThrow("Failed to fetch metrics: 403");
    });
});

describe("fetchPlanInfo", () => {
    it("fetches /dashboard/plans", async () => {
        const plans = { current_plan: "pro", billing_type: "monthly", plans: {} };
        mockFetchOnce(plans);
        const result = await fetchPlanInfo("token");
        expect(result.current_plan).toBe("pro");
    });
});
