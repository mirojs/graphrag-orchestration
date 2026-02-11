import { Outlet, NavLink } from "react-router-dom";
import { useState, useCallback, useContext } from "react";
import { useTranslation } from "react-i18next";
import styles from "./Layout.module.css";

import { useLogin } from "../../authConfig";
import { LoginButton } from "../../components/LoginButton";
import { LoginContext } from "../../loginContext";

const Layout = () => {
    const { t } = useTranslation();
    const { loggedIn } = useContext(LoginContext);
    const [sidebarOpen, setSidebarOpen] = useState(false);

    const toggleSidebar = useCallback(() => setSidebarOpen(prev => !prev), []);
    const closeSidebar = useCallback(() => setSidebarOpen(false), []);

    return (
        <div className={styles.layout}>
            {/* Top header bar */}
            <header className={styles.header} role="banner">
                <div className={styles.headerContainer}>
                    <div className={styles.headerLeft}>
                        {loggedIn && (
                            <button
                                className={styles.menuToggle}
                                onClick={toggleSidebar}
                                aria-label="Toggle navigation"
                                aria-expanded={sidebarOpen}
                            >
                                <span className={styles.hamburger} />
                            </button>
                        )}
                        <NavLink to="/" className={styles.headerTitleContainer} onClick={closeSidebar}>
                            <h3 className={styles.headerTitle}>{t("headerTitle")}</h3>
                        </NavLink>
                    </div>
                    <div className={styles.loginMenuContainer}>{useLogin && <LoginButton />}</div>
                </div>
            </header>

            <div className={styles.body}>
                {/* Sidebar overlay for mobile */}
                {sidebarOpen && loggedIn && <div className={styles.sidebarOverlay} onClick={closeSidebar} />}

                {/* Sidebar navigation — only shown after login */}
                {loggedIn && (
                    <nav className={`${styles.sidebar} ${sidebarOpen ? styles.sidebarOpen : ""}`} aria-label="Main navigation">
                        <NavLink
                            to="/"
                            end
                            className={({ isActive }) => `${styles.navItem} ${isActive ? styles.navItemActive : ""}`}
                            onClick={closeSidebar}
                        >
                            <span className={styles.navIcon}>💬</span>
                            <span className={styles.navLabel}>Chat</span>
                        </NavLink>
                        <NavLink
                            to="/files"
                            className={({ isActive }) => `${styles.navItem} ${isActive ? styles.navItemActive : ""}`}
                            onClick={closeSidebar}
                        >
                            <span className={styles.navIcon}>📁</span>
                            <span className={styles.navLabel}>Files</span>
                        </NavLink>
                        <div className={styles.navDivider} />
                        <NavLink
                            to="/dashboard"
                            className={({ isActive }) => `${styles.navItem} ${isActive ? styles.navItemActive : ""}`}
                            onClick={closeSidebar}
                        >
                            <span className={styles.navIcon}>📊</span>
                            <span className={styles.navLabel}>Dashboard</span>
                        </NavLink>

                        {/* Bottom spacer pushes version to bottom */}
                        <div className={styles.navSpacer} />
                        <div className={styles.navVersion}>v2.0</div>
                    </nav>
                )}

                {/* Main content area */}
                <main className={styles.main} id="main-content">
                    <Outlet />
                </main>
            </div>
        </div>
    );
};

export default Layout;
