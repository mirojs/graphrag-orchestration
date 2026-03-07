/**
 * Dashboard API client and type definitions.
 *
 * Talks to /dashboard/* endpoints on the API gateway.
 */

import { getHeaders, fetchWithAuthRetry } from "./api";

// ============================================================================
// Types
// ============================================================================

export interface PlanLimits {
    queries_per_day: number;
    queries_per_month: number;
    max_tokens_per_query: number;
    max_documents: number;
    max_document_size_mb: number;
    max_storage_gb: number;
    monthly_credits: number | null;
    graphrag_enabled: boolean;
    advanced_analytics: boolean;
    custom_models: boolean;
    api_access: boolean;
    priority_support: boolean;
    max_users: number | null;
    sso_enabled: boolean;
    custom_branding: boolean;
    dedicated_resources: boolean;
}

export interface UserProfileResponse {
    user_id: string;
    display_name: string | null;
    email: string | null;
    tenant_id: string | null;
    roles: string[];
    is_admin: boolean;
    plan: string;
    plan_limits: PlanLimits | null;
    billing_type: string;
    queries_today: number;
    queries_this_month: number;
    documents_count: number;
    storage_used_gb: number;
    features: Record<string, boolean>;
}

export interface UsageStats {
    queries_today: number;
    queries_this_month: number;
    queries_limit_day: number;
    queries_limit_month: number;
    documents_count: number;
    documents_limit: number;
    personal_documents_count?: number;
    global_documents_count?: number;
    storage_used_gb: number;
    storage_limit_gb: number;
    credits_used_month: number;
    credits_limit_month: number | null;
    credits_remaining: number | null;
    translated_queries_month: number;
    speech_queries_month: number;
    recent_queries: Array<Record<string, any>>;
    top_topics: Array<Record<string, any>>;
}

export interface SystemMetrics {
    total_users: number;
    active_users_today: number;
    active_users_month: number;
    total_queries_today: number;
    total_queries_month: number;
    total_documents: number;
    total_storage_gb: number;
    plan_distribution: Record<string, number>;
    algorithm_version: string;
    enabled_versions: string[];
    system_status: string;
    queries_per_hour: Array<Record<string, any>>;
    top_users: Array<Record<string, any>>;
    error_rate: number;
}

export interface PlanInfo {
    current_plan: string;
    billing_type: string;
    plans: Record<string, Record<string, any>>;
}

export interface DashboardAllData {
    profile: UserProfileResponse;
    usage: UsageStats;
    plans: PlanInfo;
}

// ============================================================================
// API calls
// ============================================================================

export async function fetchDashboardAll(idToken: string | undefined): Promise<DashboardAllData> {
    const headers = await getHeaders(idToken);
    const response = await fetchWithAuthRetry("/dashboard/all", {
        method: "GET",
        headers: { ...headers, "Content-Type": "application/json" }
    });
    if (!response.ok) {
        let detail = "";
        try {
            const body = await response.json();
            detail = body.detail || body.message || "";
        } catch {
            detail = response.statusText || "";
        }
        throw new Error(`Failed to fetch dashboard (${response.status}): ${detail}`);
    }
    return response.json();
}

export async function fetchUserProfile(idToken: string | undefined): Promise<UserProfileResponse> {
    const headers = await getHeaders(idToken);
    const response = await fetchWithAuthRetry("/dashboard/me", {
        method: "GET",
        headers: { ...headers, "Content-Type": "application/json" }
    });
    if (!response.ok) {
        throw new Error(`Failed to fetch profile: ${response.status} ${response.statusText}`);
    }
    return response.json();
}

export async function fetchUsageStats(idToken: string | undefined): Promise<UsageStats> {
    const headers = await getHeaders(idToken);
    const response = await fetchWithAuthRetry("/dashboard/me/usage", {
        method: "GET",
        headers: { ...headers, "Content-Type": "application/json" }
    });
    if (!response.ok) {
        let detail = "";
        try {
            const body = await response.json();
            detail = body.detail || body.message || "";
        } catch {
            detail = response.statusText || "";
        }
        throw new Error(`Failed to fetch usage (${response.status}): ${detail}`);
    }
    return response.json();
}

export async function fetchSystemMetrics(idToken: string | undefined): Promise<SystemMetrics> {
    const headers = await getHeaders(idToken);
    const response = await fetchWithAuthRetry("/dashboard/admin/metrics", {
        method: "GET",
        headers: { ...headers, "Content-Type": "application/json" }
    });
    if (!response.ok) {
        throw new Error(`Failed to fetch metrics: ${response.status} ${response.statusText}`);
    }
    return response.json();
}

export async function fetchPlanInfo(idToken: string | undefined): Promise<PlanInfo> {
    const headers = await getHeaders(idToken);
    const response = await fetchWithAuthRetry("/dashboard/plans", {
        method: "GET",
        headers: { ...headers, "Content-Type": "application/json" }
    });
    if (!response.ok) {
        throw new Error(`Failed to fetch plans: ${response.status} ${response.statusText}`);
    }
    return response.json();
}
