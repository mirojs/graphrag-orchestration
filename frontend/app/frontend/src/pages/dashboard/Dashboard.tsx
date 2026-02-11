import { useEffect, useState, useContext } from "react";
import { Link } from "react-router-dom";
import { useMsal } from "@azure/msal-react";
import styles from "./Dashboard.module.css";
import { useLogin, getToken } from "../../authConfig";
import { LoginContext } from "../../loginContext";
import { fetchUserProfile, fetchUsageStats, fetchPlanInfo, UserProfileResponse, UsageStats, PlanInfo } from "../../api/dashboard";

const PLAN_BADGE_CLASS: Record<string, string> = {
    free: styles.planFree,
    starter: styles.planStarter,
    professional: styles.planProfessional,
    enterprise: styles.planEnterprise
};

const FEATURE_LABELS: Record<string, string> = {
    graphrag: "GraphRAG Search",
    advanced_analytics: "Advanced Analytics",
    custom_models: "Custom Models",
    api_access: "API Access",
    priority_support: "Priority Support",
    sso: "SSO Integration",
    custom_branding: "Custom Branding"
};

function usePct(used: number, limit: number): { pct: number; color: string } {
    if (limit <= 0) return { pct: 0, color: styles.barGreen };
    const pct = Math.min(100, Math.round((used / limit) * 100));
    const color = pct > 90 ? styles.barRed : pct > 70 ? styles.barYellow : styles.barGreen;
    return { pct, color };
}

const Dashboard = () => {
    const { loggedIn } = useContext(LoginContext);
    const client = useLogin ? useMsal().instance : undefined;

    const [profile, setProfile] = useState<UserProfileResponse | null>(null);
    const [usage, setUsage] = useState<UsageStats | null>(null);
    const [plans, setPlans] = useState<PlanInfo | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!loggedIn) {
            setLoading(false);
            return;
        }

        const load = async () => {
            try {
                const token = client ? await getToken(client) : undefined;
                const [profileData, usageData, planData] = await Promise.all([
                    fetchUserProfile(token),
                    fetchUsageStats(token),
                    fetchPlanInfo(token)
                ]);
                setProfile(profileData);
                setUsage(usageData);
                setPlans(planData);
            } catch (e: any) {
                setError(e.message || "Failed to load dashboard");
            } finally {
                setLoading(false);
            }
        };
        load();
    }, [loggedIn, client]);

    // --- Login required ---
    if (!loggedIn) {
        return (
            <div className={styles.loginRequired}>
                <span>🔒</span>
                <h2>Sign in Required</h2>
                <p>Please sign in to view your dashboard.</p>
            </div>
        );
    }

    // --- Loading ---
    if (loading) {
        return (
            <div className={styles.loadingContainer}>
                <div className={styles.spinner} />
            </div>
        );
    }

    // --- Error ---
    if (error) {
        return (
            <div className={styles.errorContainer}>
                <span>⚠️</span>
                <p>{error}</p>
            </div>
        );
    }

    if (!profile || !usage) return null;

    const queryDay = usePct(usage.queries_today, usage.queries_limit_day);
    const queryMonth = usePct(usage.queries_this_month, usage.queries_limit_month);
    const docs = usePct(usage.documents_count, usage.documents_limit);
    const storage = usePct(usage.storage_used_gb, usage.storage_limit_gb);

    return (
        <div className={styles.dashboardContainer}>
            {/* Header */}
            <div className={styles.dashboardHeader}>
                <div>
                    <h1 className={styles.greeting}>
                        {profile.display_name ? `Hello, ${profile.display_name}` : "Dashboard"}
                    </h1>
                    {profile.email && (
                        <span className={styles.statSubtext}>{profile.email}</span>
                    )}
                </div>
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                    <span className={`${styles.planBadge} ${PLAN_BADGE_CLASS[profile.plan] || styles.planFree}`}>
                        {profile.plan}
                    </span>
                    {profile.is_admin && (
                        <Link to="/admin" className={styles.adminLink}>
                            ⚙️ Admin Dashboard
                        </Link>
                    )}
                </div>
            </div>

            {/* Stats */}
            <div className={styles.statsGrid}>
                <div className={styles.statCard}>
                    <span className={styles.statLabel}>Queries Today</span>
                    <span className={styles.statValue}>{usage.queries_today}</span>
                    <span className={styles.statSubtext}>of {usage.queries_limit_day} daily limit</span>
                    <div className={styles.statBar}>
                        <div className={`${styles.statBarFill} ${queryDay.color}`} style={{ width: `${queryDay.pct}%` }} />
                    </div>
                </div>

                <div className={styles.statCard}>
                    <span className={styles.statLabel}>Queries This Month</span>
                    <span className={styles.statValue}>{usage.queries_this_month}</span>
                    <span className={styles.statSubtext}>of {usage.queries_limit_month} monthly limit</span>
                    <div className={styles.statBar}>
                        <div className={`${styles.statBarFill} ${queryMonth.color}`} style={{ width: `${queryMonth.pct}%` }} />
                    </div>
                </div>

                <div className={styles.statCard}>
                    <span className={styles.statLabel}>Documents</span>
                    <span className={styles.statValue}>{usage.documents_count}</span>
                    <span className={styles.statSubtext}>of {usage.documents_limit} limit</span>
                    <div className={styles.statBar}>
                        <div className={`${styles.statBarFill} ${docs.color}`} style={{ width: `${docs.pct}%` }} />
                    </div>
                </div>

                <div className={styles.statCard}>
                    <span className={styles.statLabel}>Storage Used</span>
                    <span className={styles.statValue}>{usage.storage_used_gb.toFixed(1)} GB</span>
                    <span className={styles.statSubtext}>of {usage.storage_limit_gb} GB limit</span>
                    <div className={styles.statBar}>
                        <div className={`${styles.statBarFill} ${storage.color}`} style={{ width: `${storage.pct}%` }} />
                    </div>
                </div>
            </div>

            {/* Features */}
            <div className={styles.section}>
                <h2 className={styles.sectionTitle}>Your Features</h2>
                <div className={styles.featuresGrid}>
                    {Object.entries(FEATURE_LABELS).map(([key, label]) => {
                        const enabled = profile.features[key] ?? false;
                        return (
                            <div
                                key={key}
                                className={`${styles.featureItem} ${enabled ? styles.featureEnabled : styles.featureDisabled}`}
                            >
                                <span className={styles.featureIcon}>{enabled ? "✅" : "🔒"}</span>
                                <span>{label}</span>
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Plans comparison */}
            {plans && (
                <div className={styles.section}>
                    <h2 className={styles.sectionTitle}>Plans</h2>
                    <div className={styles.planGrid}>
                        {Object.entries(plans.plans).map(([tier, info]) => {
                            const isCurrent = tier === plans.current_plan;
                            return (
                                <div
                                    key={tier}
                                    className={`${styles.planCard} ${isCurrent ? styles.planCardCurrent : ""}`}
                                >
                                    <div className={styles.planCardName}>{info.name}</div>
                                    <p className={styles.planCardDetail}>{info.queries_per_day} queries/day</p>
                                    <p className={styles.planCardDetail}>{info.max_documents} documents</p>
                                    <p className={styles.planCardDetail}>{info.max_storage_gb} GB storage</p>
                                    <p className={styles.planCardDetail}>
                                        {info.graphrag_enabled ? "✅ GraphRAG" : "❌ GraphRAG"}
                                    </p>
                                    <button className={styles.upgradeButton} disabled={isCurrent}>
                                        {isCurrent ? "Current Plan" : "Upgrade"}
                                    </button>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
};

export default Dashboard;
