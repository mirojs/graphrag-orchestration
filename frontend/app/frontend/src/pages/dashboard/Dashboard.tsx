import { useEffect, useCallback, useState, useContext } from "react";
import { Link } from "react-router-dom";
import { useMsal } from "@azure/msal-react";
import { useTranslation } from "react-i18next";
import styles from "./Dashboard.module.css";
import { useLogin, getToken, isUsingAppServicesLogin } from "../../authConfig";
import { LoginContext } from "../../loginContext";
import { fetchDashboardAll, UserProfileResponse, UsageStats, PlanInfo } from "../../api/dashboard";

const PLAN_BADGE_CLASS: Record<string, string> = {
    free: styles.planFree,
    starter: styles.planStarter,
    professional: styles.planProfessional,
    enterprise: styles.planEnterprise
};

function usePct(used: number, limit: number): { pct: number; color: string } {
    if (limit <= 0) return { pct: 0, color: styles.barGreen };
    const pct = Math.min(100, Math.round((used / limit) * 100));
    const color = pct > 90 ? styles.barRed : pct > 70 ? styles.barYellow : styles.barGreen;
    return { pct, color };
}

const Dashboard = () => {
    const { loggedIn } = useContext(LoginContext);
    const { t } = useTranslation();
    const client = useLogin ? useMsal().instance : undefined;

    const [profile, setProfile] = useState<UserProfileResponse | null>(null);
    const [usage, setUsage] = useState<UsageStats | null>(null);
    const [plans, setPlans] = useState<PlanInfo | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [sessionExpired, setSessionExpired] = useState(false);

    const handleReLogin = () => {
        if (isUsingAppServicesLogin) {
            window.location.href = ".auth/login/aad?post_login_redirect_uri=" + encodeURIComponent(window.location.pathname + window.location.search);
        } else {
            // MSAL: clear cache and reload to trigger interactive login
            client?.logoutRedirect({ postLogoutRedirectUri: window.location.pathname });
        }
    };

    const loadDashboard = useCallback(async () => {
        try {
            const token = client ? await getToken(client) : undefined;
            const data = await fetchDashboardAll(token);
            setProfile(data.profile);
            setUsage(data.usage);
            setPlans(data.plans);
        } catch (e: any) {
            const msg = e.message || "Failed to load dashboard";
            if (msg.includes("401") || msg.toLowerCase().includes("expired") || msg.toLowerCase().includes("unauthorized")) {
                setSessionExpired(true);
            } else {
                setError(msg);
            }
        } finally {
            setLoading(false);
        }
    }, [client]);

    useEffect(() => {
        if (!loggedIn) {
            setLoading(false);
            return;
        }

        loadDashboard();

        // Re-fetch when user returns to this tab (e.g. after making queries)
        const handleVisibility = () => {
            if (document.visibilityState === "visible") {
                loadDashboard();
            }
        };
        document.addEventListener("visibilitychange", handleVisibility);
        return () => document.removeEventListener("visibilitychange", handleVisibility);
    }, [loggedIn, loadDashboard]);

    // --- Login required ---
    if (!loggedIn) {
        return (
            <div className={styles.loginRequired}>
                <span>🔒</span>
                <h2>{t("dashboard.signInRequired")}</h2>
                <p>{t("dashboard.signInToView")}</p>
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

    // --- Session expired ---
    if (sessionExpired) {
        return (
            <div className={styles.loginRequired}>
                <span>🔑</span>
                <h2>{t("dashboard.sessionExpired")}</h2>
                <p>{t("dashboard.sessionExpiredMessage")}</p>
                <button className={styles.upgradeButton} onClick={handleReLogin}>
                    {t("dashboard.signIn")}
                </button>
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
    const credits = usePct(usage.credits_used_month, usage.credits_limit_month ?? 0);
    const docs = usePct(usage.documents_count, usage.documents_limit);
    const storage = usePct(usage.storage_used_gb, usage.storage_limit_gb);

    return (
        <div className={styles.dashboardContainer}>
            {/* Header */}
            <div className={styles.dashboardHeader}>
                <div>
                    <h1 className={styles.greeting}>
                        {profile.display_name ? t("dashboard.hello", { name: profile.display_name }) : t("dashboard.title")}
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
                            ⚙️ {t("dashboard.adminDashboard")}
                        </Link>
                    )}
                </div>
            </div>

            {/* Stats */}
            <div className={styles.statsGrid}>
                <div className={styles.statCard}>
                    <span className={styles.statLabel}>{t("dashboard.queriesToday")}</span>
                    <span className={styles.statValue}>{usage.queries_today}</span>
                    <span className={styles.statSubtext}>{t("dashboard.dailyLimit", { limit: usage.queries_limit_day })}</span>
                    <div className={styles.statBar}>
                        <div className={`${styles.statBarFill} ${queryDay.color}`} style={{ width: `${queryDay.pct}%` }} />
                    </div>
                </div>

                <div className={styles.statCard}>
                    <span className={styles.statLabel}>{t("dashboard.queriesThisMonth")}</span>
                    <span className={styles.statValue}>{usage.queries_this_month}</span>
                    <span className={styles.statSubtext}>{t("dashboard.monthlyLimit", { limit: usage.queries_limit_month })}</span>
                    <div className={styles.statBar}>
                        <div className={`${styles.statBarFill} ${queryMonth.color}`} style={{ width: `${queryMonth.pct}%` }} />
                    </div>
                </div>

                <div className={styles.statCard}>
                    <span className={styles.statLabel}>{t("dashboard.creditsUsed")}</span>
                    <span className={styles.statValue}>{usage.credits_used_month.toLocaleString()}</span>
                    <span className={styles.statSubtext}>
                        {usage.credits_limit_month != null ? t("dashboard.monthlyCredits", { limit: usage.credits_limit_month.toLocaleString() }) : t("dashboard.unlimitedCredits")}
                        {usage.translated_queries_month > 0 && ` · ${t("dashboard.translated", { count: usage.translated_queries_month })}`}
                        {usage.speech_queries_month > 0 && ` · ${t("dashboard.voice", { count: usage.speech_queries_month })}`}
                    </span>
                    <div className={styles.statBar}>
                        <div className={`${styles.statBarFill} ${credits.color}`} style={{ width: `${credits.pct}%` }} />
                    </div>
                </div>

                <div className={styles.statCard}>
                    <span className={styles.statLabel}>{t("dashboard.documents")}</span>
                    <span className={styles.statValue}>{usage.documents_count}</span>
                    <span className={styles.statSubtext}>
                        {usage.personal_documents_count != null && usage.global_documents_count != null
                            ? t("dashboard.personalShared", { personal: usage.personal_documents_count, shared: usage.global_documents_count, limit: usage.documents_limit })
                            : t("dashboard.ofLimit", { limit: usage.documents_limit })}
                    </span>
                    <div className={styles.statBar}>
                        <div className={`${styles.statBarFill} ${docs.color}`} style={{ width: `${docs.pct}%` }} />
                    </div>
                </div>

                <div className={styles.statCard}>
                    <span className={styles.statLabel}>{t("dashboard.storageUsed")}</span>
                    <span className={styles.statValue}>{usage.storage_used_gb.toFixed(1)} GB</span>
                    <span className={styles.statSubtext}>{t("dashboard.gbLimit", { limit: usage.storage_limit_gb })}</span>
                    <div className={styles.statBar}>
                        <div className={`${styles.statBarFill} ${storage.color}`} style={{ width: `${storage.pct}%` }} />
                    </div>
                </div>
            </div>

            {/* Recent Activity */}
            {usage.recent_queries.length > 0 && (
                <div className={styles.section}>
                    <h2 className={styles.sectionTitle}>{t("dashboard.recentActivity")}</h2>
                    <table className={styles.recentTable}>
                        <thead>
                            <tr>
                                <th>{t("dashboard.time")}</th>
                                <th>{t("dashboard.tokens")}</th>
                                <th>{t("dashboard.credits")}</th>
                                <th>{t("dashboard.language")}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {usage.recent_queries.slice(0, 10).map((q, i) => (
                                <tr key={i}>
                                    <td>{q.timestamp ? new Date(q.timestamp).toLocaleString() : "—"}</td>
                                    <td>{q.total_tokens ?? "—"}</td>
                                    <td>{q.credits_used ?? "—"}</td>
                                    <td>
                                        {q.detected_language || q.speech_detected_language
                                            ? `${q.was_speech_input ? "🎤 " : ""}${(q.speech_detected_language || q.detected_language || "").toUpperCase()}${q.was_translated ? " 🌐" : ""}`
                                            : "—"}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Features */}
            <div className={styles.section}>
                <h2 className={styles.sectionTitle}>{t("dashboard.yourFeatures")}</h2>
                <div className={styles.featuresGrid}>
                    {Object.entries({
                        graphrag: t("dashboard.featureGraphrag"),
                        advanced_analytics: t("dashboard.featureAdvancedAnalytics"),
                        custom_models: t("dashboard.featureCustomModels"),
                        api_access: t("dashboard.featureApiAccess"),
                        priority_support: t("dashboard.featurePrioritySupport"),
                        sso: t("dashboard.featureSso"),
                        custom_branding: t("dashboard.featureCustomBranding")
                    } as Record<string, string>).map(([key, label]) => {
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
                    <h2 className={styles.sectionTitle}>{t("dashboard.plans")}</h2>
                    <div className={styles.planGrid}>
                        {Object.entries(plans.plans).map(([tier, info]) => {
                            const isCurrent = tier === plans.current_plan;
                            return (
                                <div
                                    key={tier}
                                    className={`${styles.planCard} ${isCurrent ? styles.planCardCurrent : ""}`}
                                >
                                    <div className={styles.planCardName}>{info.name}</div>
                                    <p className={styles.planCardDetail}>{t("dashboard.queriesPerDay", { count: info.queries_per_day })}</p>
                                    <p className={styles.planCardDetail}>{t("dashboard.maxDocuments", { count: info.max_documents })}</p>
                                    <p className={styles.planCardDetail}>{t("dashboard.maxStorage", { count: info.max_storage_gb })}</p>
                                    <p className={styles.planCardDetail}>
                                        {info.monthly_credits != null
                                            ? t("dashboard.creditsPerMonth", { count: info.monthly_credits.toLocaleString() })
                                            : t("dashboard.unlimitedCredits")}
                                    </p>
                                    <p className={styles.planCardDetail}>
                                        {info.graphrag_enabled ? "✅ Evidoc" : "❌ Evidoc"}
                                    </p>
                                    <button
                                        className={styles.upgradeButton}
                                        disabled={isCurrent}
                                        onClick={() => { if (!isCurrent) window.location.hash = "#/dashboard#plans"; }}
                                    >
                                        {isCurrent ? t("dashboard.currentPlan") : t("dashboard.contactSales")}
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
