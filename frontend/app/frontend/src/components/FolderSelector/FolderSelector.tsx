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

const ALL_DOCUMENTS_VALUE = "__all__";

export const FolderSelector = ({ selectedFolderId, onFolderChange }: FolderSelectorProps) => {
    const { t } = useTranslation();
    const client = useLogin ? useMsal().instance : undefined;
    const [folders, setFolders] = useState<Folder[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Include both user folders that are analyzed AND analysis_result folders
    const analyzedFolders = folders.filter(
        f =>
            (f.analysis_status === "analyzed" || f.analysis_status === "stale") &&
            (f.folder_type === "user" || f.folder_type === "analysis_result")
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

    // Auto-select when exactly one analyzed folder and no folder pre-selected
    useEffect(() => {
        if (!selectedFolderId && analyzedFolders.length === 1) {
            const folder = analyzedFolders[0];
            onFolderChange(folder.analysis_group_id || folder.id);
        }
    }, [analyzedFolders.length, selectedFolderId]);

    const handleSelect = (_ev: SelectionEvents, data: OptionOnSelectData) => {
        const value = data.optionValue;
        if (value === ALL_DOCUMENTS_VALUE || !value) {
            onFolderChange(undefined);
        } else {
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
    const displayValue = selectedFolder ? `📁 ${selectedFolder.name}` : t("folderSelector.allDocuments");
    const selectedOption = selectedFolderId || ALL_DOCUMENTS_VALUE;

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
                <Option key={ALL_DOCUMENTS_VALUE} value={ALL_DOCUMENTS_VALUE} text={t("folderSelector.allDocuments")}>
                    {t("folderSelector.allDocuments")}
                </Option>
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
