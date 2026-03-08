/**
 * FolderSidebar — hierarchical folder navigation panel
 *
 * Shows a tree of folders (max 2 levels) with:
 * - "All Files" root node
 * - Create folder button
 * - Inline rename on double-click
 * - Delete via context action
 */

import { useState, useCallback, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import type { Folder } from "../../api/folders";
import styles from "./FolderSidebar.module.css";

interface FolderSidebarProps {
    folders: Folder[];
    activeFolderId: string | null;
    onSelectFolder: (folderId: string | null) => void;
    onCreateFolder: (name: string, parentId: string | null) => void;
    onRenameFolder: (folderId: string, newName: string) => void;
    onDeleteFolder: (folderId: string) => void;
}

export const FolderSidebar = ({
    folders,
    activeFolderId,
    onSelectFolder,
    onCreateFolder,
    onRenameFolder,
    onDeleteFolder,
}: FolderSidebarProps) => {
    const { t } = useTranslation();
    const [creating, setCreating] = useState<{ parentId: string | null } | null>(null);
    const [newFolderName, setNewFolderName] = useState("");
    const [renamingId, setRenamingId] = useState<string | null>(null);
    const [renameValue, setRenameValue] = useState("");
    const [contextMenu, setContextMenu] = useState<{ folderId: string; x: number; y: number } | null>(null);
    const createInputRef = useRef<HTMLInputElement>(null);
    const renameInputRef = useRef<HTMLInputElement>(null);

    const rootFolders = folders.filter(f => !f.parent_folder_id);
    const childrenOf = (parentId: string) => folders.filter(f => f.parent_folder_id === parentId);

    useEffect(() => {
        if (creating) createInputRef.current?.focus();
    }, [creating]);

    useEffect(() => {
        if (renamingId) renameInputRef.current?.focus();
    }, [renamingId]);

    // Close context menu on click outside
    useEffect(() => {
        if (!contextMenu) return;
        const handler = () => setContextMenu(null);
        document.addEventListener("click", handler);
        return () => document.removeEventListener("click", handler);
    }, [contextMenu]);

    const handleCreateSubmit = useCallback(() => {
        const name = newFolderName.trim();
        if (name) {
            onCreateFolder(name, creating?.parentId ?? null);
        }
        setCreating(null);
        setNewFolderName("");
    }, [newFolderName, creating, onCreateFolder]);

    const handleRenameSubmit = useCallback(() => {
        const name = renameValue.trim();
        if (name && renamingId) {
            onRenameFolder(renamingId, name);
        }
        setRenamingId(null);
        setRenameValue("");
    }, [renameValue, renamingId, onRenameFolder]);

    const startRename = (folder: Folder) => {
        setRenamingId(folder.id);
        setRenameValue(folder.name);
        setContextMenu(null);
    };

    const handleContextMenu = (e: React.MouseEvent, folderId: string) => {
        e.preventDefault();
        e.stopPropagation();
        setContextMenu({ folderId, x: e.clientX, y: e.clientY });
    };

    const handleCreateCancel = useCallback(() => {
        setCreating(null);
        setNewFolderName("");
    }, []);

    const renderCreateInput = () => (
        <div className={styles.createRow}>
            <span className={styles.folderIcon}>📁</span>
            <input
                ref={createInputRef}
                className={styles.inlineInput}
                value={newFolderName}
                onChange={e => setNewFolderName(e.target.value)}
                onKeyDown={e => {
                    if (e.key === "Enter") handleCreateSubmit();
                    if (e.key === "Escape") handleCreateCancel();
                }}
                placeholder={t("files.folderNamePlaceholder")}
            />
            <button
                className={styles.inlineConfirmBtn}
                onClick={handleCreateSubmit}
                title={t("files.confirm")}
            >
                ✓
            </button>
            <button
                className={styles.inlineCancelBtn}
                onClick={handleCreateCancel}
                title={t("files.cancel")}
            >
                ✕
            </button>
        </div>
    );

    const renderFolder = (folder: Folder, depth: number) => {
        const isActive = activeFolderId === folder.id;
        const isRenaming = renamingId === folder.id;
        const children = childrenOf(folder.id);

        return (
            <div key={folder.id}>
                <div
                    className={`${styles.folderRow} ${isActive ? styles.folderRowActive : ""}`}
                    style={{ paddingLeft: 12 + depth * 20 }}
                    onClick={() => onSelectFolder(folder.id)}
                    onContextMenu={e => handleContextMenu(e, folder.id)}
                >
                    <span className={styles.folderIcon}>{children.length > 0 ? "📂" : "📁"}</span>
                    {isRenaming ? (
                        <>
                            <input
                                ref={renameInputRef}
                                className={styles.inlineInput}
                                value={renameValue}
                                onChange={e => setRenameValue(e.target.value)}
                                onKeyDown={e => {
                                    if (e.key === "Enter") handleRenameSubmit();
                                    if (e.key === "Escape") { setRenamingId(null); setRenameValue(""); }
                                }}
                                onClick={e => e.stopPropagation()}
                            />
                            <button
                                className={styles.inlineConfirmBtn}
                                onClick={e => { e.stopPropagation(); handleRenameSubmit(); }}
                                title={t("files.confirm")}
                            >
                                ✓
                            </button>
                            <button
                                className={styles.inlineCancelBtn}
                                onClick={e => { e.stopPropagation(); setRenamingId(null); setRenameValue(""); }}
                                title={t("files.cancel")}
                            >
                                ✕
                            </button>
                        </>
                    ) : (
                        <span className={styles.folderName} title={folder.name}>{folder.name}</span>
                    )}
                    {!isRenaming && (
                        <button
                            className={styles.moreBtn}
                            onClick={e => { e.stopPropagation(); handleContextMenu(e, folder.id); }}
                            title={t("files.folderActions")}
                        >
                            ⋯
                        </button>
                    )}
                </div>
                {children.map(child => renderFolder(child, depth + 1))}
                {creating && creating.parentId === folder.id && renderCreateInput()}
            </div>
        );
    };

    return (
        <div className={styles.sidebar}>
            <div className={styles.sidebarHeader}>
                <span className={styles.sidebarTitle}>{t("files.folders")}</span>
                <button
                    className={styles.newFolderBtn}
                    onClick={() => { setCreating({ parentId: null }); setNewFolderName(""); }}
                    title={t("files.newFolder")}
                >
                    +
                </button>
            </div>

            {/* All Files (root) */}
            <div
                className={`${styles.folderRow} ${activeFolderId === null ? styles.folderRowActive : ""}`}
                onClick={() => onSelectFolder(null)}
            >
                <span className={styles.folderIcon}>🏠</span>
                <span className={styles.folderName} title={t("files.allFiles")}>{t("files.allFiles")}</span>
            </div>

            {rootFolders.map(f => renderFolder(f, 0))}
            {creating && creating.parentId === null && renderCreateInput()}

            {/* Context menu */}
            {contextMenu && (
                <div
                    className={styles.contextMenu}
                    style={{ top: contextMenu.y, left: contextMenu.x }}
                >
                    {(() => {
                        const folder = folders.find(f => f.id === contextMenu.folderId);
                        const isRoot = folder && !folder.parent_folder_id;
                        return (
                            <>
                                <button onClick={() => startRename(folder!)}>✏️ {t("files.rename")}</button>
                                {isRoot && (
                                    <button onClick={() => {
                                        setCreating({ parentId: contextMenu.folderId });
                                        setNewFolderName("");
                                        setContextMenu(null);
                                    }}>📁 {t("files.newSubfolder")}</button>
                                )}
                                <button
                                    className={styles.contextMenuDanger}
                                    onClick={() => { onDeleteFolder(contextMenu.folderId); setContextMenu(null); }}
                                >
                                    🗑️ {t("files.delete")}
                                </button>
                            </>
                        );
                    })()}
                </div>
            )}
        </div>
    );
};
