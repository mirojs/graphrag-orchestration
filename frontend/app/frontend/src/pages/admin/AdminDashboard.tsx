import { useEffect, useState, useContext } from "react";
import { Link } from "react-router-dom";
import { useMsal } from "@azure/msal-react";
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
                <h2>Sign in Required</h2>
                <Link to="/dashboard" className={styles.backLink}>Go to Dashboard</Link>
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
                <h2>Admin Access Required</h2>
                <p>You need the Admin role to view this dashboard.</p>
                <Link to="/dashboard" className={styles.backLink}>← Back to Dashboard</Link>
            </div>
        );
    }

    // --- Error ---
    if (error) {
        return (
            <div className={styles.forbiddenContainer}>
                <span style={{ fontSize: "2.5rem" }}>⚠️</span>
                <p>{error}</p>
                <Link to="/dashboard" className={styles.backLink}>← Back to Dashboard</Link>
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
                    <h1 className={styles.adminTitle}>Management Dashboard</h1>
                    <Link to="/dashboard" className={styles.backLink}>← Personal Dashboard</Link>
                </div>
                <span className={`${styles.statusBadge} ${STATUS_CLASS[metrics.system_status] || styles.statusHealthy}`}>
                    {metrics.system_status === "healthy" ? "●" : "⚠"} {metrics.system_status}
                </span>
            </div>

            {/* Key Metrics */}
            <div className={styles.metricsGrid}>
                <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>Total Users</span>
                    <span className={styles.metricValue}>{metrics.total_users}</span>
                </div>
                <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>Active Today</span>
                    <span className={styles.metricValue}>{metrics.active_users_today}</span>
                </div>
                <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>Queries Today</span>
                    <span className={styles.metricValue}>{metrics.total_queries_today}</span>
                </div>
                <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>Queries This Month</span>
                    <span className={styles.metricValue}>{metrics.total_queries_month}</span>
                </div>
                <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>Total Documents</span>
                    <span className={styles.metricValue}>{metrics.total_documents}</span>
                </div>
                <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>Storage Used</span>
                    <span className={styles.metricValue}>{metrics.total_storage_gb.toFixed(1)} GB</span>
                </div>
                <div className={styles.metricCard}>
                    <span className={styles.metricLabel}>Error Rate</span>
                    <span className={styles.metricValue}>{(metrics.error_rate * 100).toFixed(1)}%</span>
                </div>
            </div>

            {/* Algorithm versions */}
            <div className={styles.section}>
                <h2 className={styles.sectionTitle}>Algorithm Versions</h2>
                <div className={styles.versionRow}>
                    {metrics.enabled_versions.map(v => (
                        <span
                            key={v}
                            className={`${styles.versionPill} ${v === metrics.algorithm_version ? styles.versionDefault : ""}`}
                        >
                            {v}
                            {v === metrics.algorithm_version && " (default)"}
                        </span>
                    ))}
                </div>
                <span className={styles.metricSub}>
                    Default: {metrics.algorithm_version} · {metrics.enabled_versions.length} enabled
                </span>
            </div>

            {/* Plan distribution */}
            <div className={styles.section}>
                <h2 className={styles.sectionTitle}>Plan Distribution</h2>
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

            {/* Top users placeholder */}
            <div className={styles.section}>
                <h2 className={styles.sectionTitle}>Top Users</h2>
                <table className={styles.userList}>
                    <thead>
                        <tr>
                            <th>User</th>
                            <th>Queries</th>
                            <th>Plan</th>
                            <th>Last Active</th>
                        </tr>
                    </thead>
                    <tbody>
                        {metrics.top_users.length === 0 ? (
                            <tr>
                                <td colSpan={4} className={styles.emptyRow}>
                                    No user activity data yet. Data will appear once analytics are connected.
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
