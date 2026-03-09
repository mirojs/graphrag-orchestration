import { useTranslation } from "react-i18next";

import type { AnalysisStatus } from "../../api/folders";
import styles from "../../pages/files/Files.module.css";

interface FileToolbarProps {
    fileCount: number;
    selectedCount: number;
    searchQuery: string;
    onSearchChange: (q: string) => void;
    sortBy: "name" | "ext";
    sortAsc: boolean;
    onSortChange: (by: "name" | "ext") => void;
    onSelectAll: () => void;
    onSelectNone: () => void;
    onDeleteSelected: () => void;
    onRefresh: () => void;
    activeFolderId?: string | null;
    analysisStatus?: AnalysisStatus | null;
    isUserFolder?: boolean;
    onAnalyzeFolder?: () => void;
}

export const FileToolbar = ({
    fileCount,
    selectedCount,
    searchQuery,
    onSearchChange,
    sortBy,
    sortAsc,
    onSortChange,
    onSelectAll,
    onSelectNone,
    onDeleteSelected,
    onRefresh,
    activeFolderId,
    analysisStatus,
    isUserFolder,
    onAnalyzeFolder,
}: FileToolbarProps) => {
    const { t } = useTranslation();
    const arrow = sortAsc ? "↑" : "↓";

    return (
        <div className={styles.toolbar}>
            <input
                className={styles.searchBox}
                type="text"
                placeholder={t("fileToolbar.searchPlaceholder")}
                value={searchQuery}
                onChange={(e) => onSearchChange(e.target.value)}
            />

            <span className={styles.toolbarMeta}>
                {t("fileToolbar.fileCount", { count: fileCount })}
                {selectedCount > 0 && ` · ${t("fileToolbar.selected", { count: selectedCount })}`}
            </span>

            <button
                className={`${styles.toolbarBtn} ${sortBy === "name" ? styles.sortActive : ""}`}
                onClick={() => onSortChange("name")}
                title={t("fileToolbar.sortByName")}
            >
                {t("fileToolbar.name")} {sortBy === "name" ? arrow : ""}
            </button>

            <button
                className={`${styles.toolbarBtn} ${sortBy === "ext" ? styles.sortActive : ""}`}
                onClick={() => onSortChange("ext")}
                title={t("fileToolbar.sortByType")}
            >
                {t("fileToolbar.type")} {sortBy === "ext" ? arrow : ""}
            </button>

            {selectedCount > 0 ? (
                <>
                    <button className={styles.toolbarBtn} onClick={onSelectNone}>
                        {t("fileToolbar.deselect")}
                    </button>
                    <button className={styles.toolbarBtnDanger} onClick={onDeleteSelected}>
                        🗑️ {t("fileToolbar.delete", { count: selectedCount })}
                    </button>
                </>
            ) : (
                <button className={styles.toolbarBtn} onClick={onSelectAll}>
                    {t("fileToolbar.selectAll")}
                </button>
            )}

            <button className={styles.toolbarBtn} onClick={onRefresh} title={t("fileToolbar.refresh")}>
                🔄
            </button>

            {/* Analyze action — stale: re-analyze toolbar button; analyzing: disabled status */}
            {activeFolderId && isUserFolder && onAnalyzeFolder && (
                analysisStatus === "analyzing" ? (
                    <button className={styles.toolbarBtnAnalyzing} disabled>
                        ⏳ {t("files.analyzing", "Analyzing…")}
                    </button>
                ) : analysisStatus === "stale" ? (
                    <button className={styles.toolbarBtnAnalyze} onClick={onAnalyzeFolder}>
                        🔍 {t("files.reanalyze", "Re-analyze")}
                    </button>
                ) : null
            )}
        </div>
    );
};
