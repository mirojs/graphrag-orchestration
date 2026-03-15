import { useTranslation } from "react-i18next";
import { getFileIcon } from "../../api/files";
import { SubfolderCount } from "../../api/folders";
import styles from "../../pages/files/Files.module.css";

interface FileListProps {
    files: string[];
    selected: Set<string>;
    loading: boolean;
    onToggleSelect: (filename: string) => void;
    onDelete: (filename: string) => void;
    onRename: (filename: string) => void;
    onMove?: (filename: string) => void;
    onPreview?: (filename: string) => void;
    subfolderCounts?: SubfolderCount[];
}

export const FileList = ({ files, selected, loading, onToggleSelect, onDelete, onRename, onMove, onPreview, subfolderCounts }: FileListProps) => {
    const { t } = useTranslation();

    if (loading) {
        return (
            <div className={styles.loading}>
                <span className={styles.spinner} />
                {t("files.loadingFiles")}
            </div>
        );
    }

    if (files.length === 0) {
        const hasSubfolderFiles = subfolderCounts && subfolderCounts.length > 0
            && subfolderCounts.some(s => s.count > 0);

        if (hasSubfolderFiles) {
            const totalFiles = subfolderCounts!.reduce((sum, s) => sum + s.count, 0);
            return (
                <div className={styles.emptyState}>
                    <span className={styles.emptyIcon}>📂</span>
                    <h2>{t("files.noDirectFiles", "No files in this folder")}</h2>
                    <p style={{ marginBottom: 12 }}>
                        {t("files.subfolderSummary", {
                            defaultValue: "{{total}} file(s) across {{count}} subfolder(s):",
                            total: totalFiles,
                            count: subfolderCounts!.length,
                        })}
                    </p>
                    <div className={styles.subfolderBreakdown}>
                        {subfolderCounts!.map(s => (
                            <div key={s.name} className={styles.subfolderRow}>
                                <span className={styles.subfolderIcon}>📁</span>
                                <span className={styles.subfolderName}>{s.name}</span>
                                <span className={styles.subfolderCount}>
                                    {t("files.fileCount", { defaultValue: "{{count}} file(s)", count: s.count })}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            );
        }

        return (
            <div className={styles.emptyState}>
                <span className={styles.emptyIcon}>📂</span>
                <h2>{t("files.noFilesYet")}</h2>
                <p>{t("files.uploadFilesHint")}</p>
            </div>
        );
    }

    const getExt = (name: string) => {
        const i = name.lastIndexOf(".");
        return i > 0 ? name.slice(i + 1).toUpperCase() : "—";
    };

    return (
        <div className={styles.fileListWrapper}>
            <table className={styles.fileListTable}>
                <thead>
                    <tr>
                        <th style={{ width: 40 }}></th>
                        <th></th>
                        <th>{t("files.nameColumn")}</th>
                        <th style={{ width: 80 }}>{t("files.typeColumn")}</th>
                        <th style={{ width: 160 }}>{t("files.actionsColumn")}</th>
                    </tr>
                </thead>
                <tbody>
                    {files.map((f) => {
                        const isSelected = selected.has(f);
                        return (
                            <tr
                                key={f}
                                className={`${styles.fileRow} ${isSelected ? styles.fileRowSelected : ""}`}
                                onClick={() => onToggleSelect(f)}
                            >
                                <td>
                                    <input
                                        type="checkbox"
                                        className={styles.fileCheckbox}
                                        checked={isSelected}
                                        onChange={() => onToggleSelect(f)}
                                        onClick={(e) => e.stopPropagation()}
                                    />
                                </td>
                                <td style={{ width: 36, textAlign: "center" }}>
                                    <span className={styles.fileIcon}>{getFileIcon(f)}</span>
                                </td>
                                <td className={styles.fileName}>
                                    <span
                                        className={styles.fileNameLink}
                                        onClick={(e) => { e.stopPropagation(); onPreview?.(f); }}
                                        title={t("files.preview")}
                                    >
                                        {f}
                                    </span>
                                </td>
                                <td className={styles.fileExt}>{getExt(f)}</td>
                                <td>
                                    <div className={styles.fileActions} onClick={(e) => e.stopPropagation()}>
                                        {onPreview && (
                                            <button
                                                className={styles.actionBtn}
                                                onClick={() => onPreview(f)}
                                                title={t("files.preview")}
                                            >
                                                👁️
                                            </button>
                                        )}
                                        {onMove && (
                                            <button
                                                className={styles.actionBtn}
                                                onClick={() => onMove(f)}
                                                title={t("files.moveToFolder")}
                                            >
                                                📁
                                            </button>
                                        )}
                                        <button
                                            className={styles.actionBtn}
                                            onClick={() => onRename(f)}
                                            title={t("files.rename")}
                                        >
                                            ✏️
                                        </button>
                                        <button
                                            className={`${styles.actionBtn} ${styles.actionBtnDanger}`}
                                            onClick={() => onDelete(f)}
                                            title={t("files.delete")}
                                        >
                                            🗑️
                                        </button>
                                    </div>
                                </td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
};
