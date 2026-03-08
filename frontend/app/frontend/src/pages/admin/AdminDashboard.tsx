import { useEffect, useState, useContext } from "react";
import { Link } from "react-router-dom";
import { useMsal } from "@azure/msal-react";
import { useTranslation } from "react-i18next";
import styles from "./AdminDashboard.module.css";
import { useLogin, getToken } from "../../authConfig";
import { LoginContext } from "../../loginContext";
import { fetchSystemMetrics, fetchUserProfile, SystemMetrics, UserProfileResponse } from "../../api/dashboard";

const STATUS_CLASS: Record<string, string> = {
    healthy: styles.statusHealthy,
    degraded: styles.statusDegraded,
    unhealthy: styles.statusUnhealthy
};

const FILL_CLASS: Record<string, string> = {
    free: styles.fillFree,
    starter: styles.fillStarter,
    professional: styles.fillProfessional,
    enterprise: styles.fillEnterprise
};

const AdminDashboard = () => {
    const { loggedIn } = useContext(LoginContext);
    const { t } = useTranslation();
    const client = useLogin ? useMsal().instance : undefined;

    const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
    const [profile, setProfile] = useState<UserProfileResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [forbidden, setForbidden] = useState(false);

    useEffect(() => {
        if (!loggedIn) {
            setLoading(false);
            return;
        }

        const load = async () => {
            try {
                const token = client ? await getToken(client) : undefined;

                // First check if user is admin
                const profileData = await fetchUserProfile(token);
                setProfile(profileData);

                if (!profileData.is_admin) {
                    setForbidden(true);
                    setLoading(false);
                    return;
                }

                const metricsData = await fetchSystemMetrics(token);
                setMetrics(metricsData);
            } catch (e: any) {
                if (e.message?.includes("403")) {
                    setForbidden(true);
                } else {
                    setError(e.message || "Failed to load admin dashboard");
                }
            } finally {
                setLoading(false);
            }
        };
        load();
    }, [loggedIn, client]);

    // --- Not logged in ---
    if (!loggedIn) {
        return (
            <div className={styles.forbiddenContainer}>
                <span style={{ fontSize: "2.5rem" }}>🔒</span>
                <h2>{t("admin.signInRequired")}</h2>
                <Link to="/dashboard" className={styles.backLink}>{t("admin.goToDashboard")}</Link>
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

    // --- Forbidden ---
    if (forbidden) {
        return (
            <div className={styles.forbiddenContainer}>
                <span style={{ fontSize: "2.5rem" }}>🚫</span>
                <h2>{t("admin.adminAccessRequired")}</h2>
                <p>{t("admin.adminRoleNeeded")}</p>
                <Link to="/dashboard" className={styles.backLink}>{t("admin.backToDashboard")}</Link>
            </div>
        );
    }

    // --- Error ---
    if (error) {
        return (
            <div className={styles.forbiddenContainer}>
                <span style={{ fontSize: "2.5rem" }}>⚠️</span>
                <p>{error}</p>
                <Link to="/dashboard" className={styles.backLink}>{t("admin.backToDashboard")}</Link>
            </div>
        );
    }

    if (!metrics) return null;

    const totalPlanUsers = Object.values(metrics.plan_distribution).reduce((a, b) => a + b, 0);

    return (
        <div className={styles.adminContainer}>
            {/* Header */}
            <div className={styles.adminHeader}>
                <div>
                    <h1 className={styles.adminTitle}>{t("admin.managementDashboard")}</h1>
                    <Link to="/dashboard" className={styles.backLink}>{t("admin.personalDashboard")}</Link>
                </div>
                <span className={`${styles.statusBadge} ${STATUS_CLASS[metrics.system_status] || styles.statusHealthy}`}>
                    {metrics.system_status === "healthy" ? "●" : "⚠"} {metrics.system_status}
                </span>
            </div>

            {/* Key Metrics */}
            <div className={styles.metricsGrid}>
                <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>{t("admin.totalUsers")}</span>
                    <span className={styles.metricValue}>{metrics.total_users}</span>
                </div>
                <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>{t("admin.activeToday")}</span>
                    <span className={styles.metricValue}>{metrics.active_users_today}</span>
                </div>
                <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>{t("admin.queriesToday")}</span>
                    <span className={styles.metricValue}>{metrics.total_queries_today}</span>
                </div>
                <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>{t("admin.queriesThisMonth")}</span>
                    <span className={styles.metricValue}>{metrics.total_queries_month}</span>
                </div>
                <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>{t("admin.totalDocuments")}</span>
                    <span className={styles.metricValue}>{metrics.total_documents}</span>
                </div>
                <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>{t("admin.storageUsed")}</span>
                    <span className={styles.metricValue}>{metrics.total_storage_gb.toFixed(1)} GB</span>
                </div>
                <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>{t("admin.errorRate")}</span>
                    <span className={styles.metricValue}>{(metrics.error_rate * 100).toFixed(1)}%</span>
                </div>
            </div>

            {/* Algorithm versions */}
            <div className={styles.section}>
                <h2 className={styles.sectionTitle}>{t("admin.algorithmVersions")}</h2>
                <div className={styles.versionRow}>
                    {metrics.enabled_versions.map(v => (
                        <span
                            key={v}
                            className={`${styles.versionPill} ${v === metrics.algorithm_version ? styles.versionDefault : ""}`}
                        >
                            {v}
                            {v === metrics.algorithm_version && ` ${t("admin.default")}`}
                        </span>
                    ))}
                </div>
                <span className={styles.metricSub}>
                    {t("admin.defaultVersion", { version: metrics.algorithm_version, count: metrics.enabled_versions.length })}
                </span>
            </div>

            {/* Plan distribution */}
            <div className={styles.section}>
                <h2 className={styles.sectionTitle}>{t("admin.planDistribution")}</h2>
                {Object.entries(metrics.plan_distribution).map(([plan, count]) => {
                    const pct = totalPlanUsers > 0 ? Math.round((count / totalPlanUsers) * 100) : 0;
                    return (
                        <div key={plan} className={styles.planDistRow}>
                            <span className={styles.planDistLabel}>{plan}</span>
                            <div className={styles.planDistBar}>
                                <div
                                    className={`${styles.planDistFill} ${FILL_CLASS[plan] || styles.fillFree}`}
                                    style={{ width: `${pct}%` }}
                                />
                            </div>
                            <span className={styles.planDistCount}>{count}</span>
                        </div>
                    );
                })}
            </div>

            {/* Queries per hour */}
            {metrics.queries_per_hour.length > 0 && (
                <div className={styles.section}>
                    <h2 className={styles.sectionTitle}>{t("admin.queriesPerHour")}</h2>
                    <div className={styles.hourChart}>
                        {(() => {
                            const maxCount = Math.max(...metrics.queries_per_hour.map(h => h.count || 0), 1);
                            return metrics.queries_per_hour.map((h, i) => (
                                <div key={i} className={styles.hourBar} title={`${h.hour}: ${h.count} queries`}>
                                    <div
                                        className={styles.hourBarFill}
                                        style={{ height: `${Math.round(((h.count || 0) / maxCount) * 100)}%` }}
                                    />
                                    <span className={styles.hourLabel}>{(h.hour || "").slice(-2)}h</span>
                                </div>
                            ));
                        })()}
                    </div>
                </div>
            )}

            {/* Top users */}
            <div className={styles.section}>
                <h2 className={styles.sectionTitle}>{t("admin.topUsers")}</h2>
                <table className={styles.userList}>
                    <thead>
                        <tr>
                            <th>{t("admin.user")}</th>
                            <th>{t("admin.queries")}</th>
                            <th>{t("admin.plan")}</th>
                            <th>{t("admin.lastActive")}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {metrics.top_users.length === 0 ? (
                            <tr>
                                <td colSpan={4} className={styles.emptyRow}>
                                    {t("admin.noUserActivity")}
                                </td>
                            </tr>
                        ) : (
                            metrics.top_users.map((u, i) => (
                                <tr key={i}>
                                    <td>{u.name || u.user_id}</td>
                                    <td>{u.queries}</td>
                                    <td>{u.plan}</td>
                                    <td>{u.last_active}</td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

export default AdminDashboard;
