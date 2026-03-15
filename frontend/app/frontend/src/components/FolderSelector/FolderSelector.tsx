import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Dropdown, Option, Spinner } from "@fluentui/react-components";
import type { OptionOnSelectData, SelectionEvents } from "@fluentui/react-components";
import { useMsal } from "@azure/msal-react";

import { useLogin, getToken } from "../../authConfig";
import { listFoldersApi } from "../../api/folders";
import type { Folder } from "../../api/folders";
import styles from "./FolderSelector.module.css";

interface FolderSelectorProps {
    selectedFolderId: string | undefined;
    onFolderChange: (folderId: string | undefined) => void;
}

export const FolderSelector = ({ selectedFolderId, onFolderChange }: FolderSelectorProps) => {
    const { t } = useTranslation();
    const client = useLogin ? useMsal().instance : undefined;
    const [folders, setFolders] = useState<Folder[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Only show top-level user folders that have been analyzed
    // (subfolders inherit analysis_status but are part of the parent's knowledge base)
    const analyzedFolders = folders.filter(
        f =>
            f.folder_type === "user" &&
            !f.parent_folder_id &&
            (f.analysis_status === "analyzed" || f.analysis_status === "stale")
    );

    const loadFolders = useCallback(async () => {
        try {
            setLoading(true);
            setError(null);
            const token = client ? await getToken(client) : undefined;
            const result = await listFoldersApi(token as string);
            setFolders(result);
        } catch (e) {
            console.error("Failed to load folders:", e);
            setError(String(e));
        } finally {
            setLoading(false);
        }
    }, [client]);

    useEffect(() => {
        loadFolders();
    }, [loadFolders]);

    // Auto-select the first analyzed folder when none is pre-selected
    useEffect(() => {
        if (!selectedFolderId && analyzedFolders.length > 0) {
            const folder = analyzedFolders[0];
            onFolderChange(folder.analysis_group_id || folder.id);
        }
    }, [analyzedFolders.length, selectedFolderId]);

    const handleSelect = (_ev: SelectionEvents, data: OptionOnSelectData) => {
        const value = data.optionValue;
        if (value) {
            onFolderChange(value);
        }
    };

    if (loading) {
        return (
            <div className={styles.container}>
                <label className={styles.label}>{t("folderSelector.label")}</label>
                <Spinner size="tiny" />
            </div>
        );
    }

    if (error) {
        return (
            <div className={styles.container}>
                <label className={styles.label}>{t("folderSelector.label")}</label>
                <span className={styles.errorText}>⚠ {t("folderSelector.loadError")}</span>
            </div>
        );
    }

    if (analyzedFolders.length === 0) {
        return (
            <div className={styles.container}>
                <label className={styles.label}>{t("folderSelector.label")}</label>
                <span className={styles.emptyText}>{t("folderSelector.noFolders")}</span>
            </div>
        );
    }

    const selectedFolder = analyzedFolders.find(
        f => (f.analysis_group_id || f.id) === selectedFolderId
    );
    const displayValue = selectedFolder ? `📁 ${selectedFolder.name}` : t("folderSelector.placeholder");
    const selectedOption = selectedFolderId || "";

    return (
        <div className={styles.container}>
            <label className={styles.label}>{t("folderSelector.label")}</label>
            <Dropdown
                className={styles.dropdown}
                placeholder={t("folderSelector.placeholder")}
                selectedOptions={[selectedOption]}
                value={displayValue}
                onOptionSelect={handleSelect}
                size="small"
            >
                {analyzedFolders.map(folder => {
                    const label = `📁 ${folder.name}${folder.analysis_status === "stale" ? " ⚠" : ""}`;
                    return (
                        <Option key={folder.id} value={folder.analysis_group_id || folder.id} text={label}>
                            {label}
                        </Option>
                    );
                })}
            </Dropdown>
        </div>
    );
};
