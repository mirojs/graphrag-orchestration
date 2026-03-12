/**
 * FolderSidebar — hierarchical folder navigation panel
 *
 * Shows a tree of folders (unlimited depth) with:
 * - "All Files" root node
 * - Create folder button
 * - Inline rename on double-click
 * - Delete via context action
 * - Analyze folder action (triggers Neo4j indexing)
 * - Analysis status badges (analyzing / analyzed / stale)
 */

import { useState, useCallback, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import type { Folder, AnalysisStatus } from "../../api/folders";
import styles from "./FolderSidebar.module.css";

interface FolderSidebarProps {
    folders: Folder[];
    activeFolderId: string | null;
    onSelectFolder: (folderId: string | null) => void;
    onCreateFolder: (name: string, parentId: string | null) => void;
    onRenameFolder: (folderId: string, newName: string) => void;
    onDeleteFolder: (folderId: string) => void;
    onAnalyzeFolder?: (folderId: string) => void;
    onChatWithAnalysis?: (folderId: string) => void;
    onDeleteAnalysis?: (folderId: string) => void;
}

export const FolderSidebar = ({
    folders,
    activeFolderId,
    onSelectFolder,
    onCreateFolder,
    onRenameFolder,
    onDeleteFolder,
    onAnalyzeFolder,
    onChatWithAnalysis,
    onDeleteAnalysis,
}: FolderSidebarProps) => {
    const { t } = useTranslation();
    const [creating, setCreating] = useState<{ parentId: string | null } | null>(null);
    const [newFolderName, setNewFolderName] = useState("");
    const [renamingId, setRenamingId] = useState<string | null>(null);
    const [renameValue, setRenameValue] = useState("");
    const [contextMenu, setContextMenu] = useState<{ folderId: string; x: number; y: number } | null>(null);
    const [collapsedZones, setCollapsedZones] = useState<Record<string, boolean>>({});
    const createInputRef = useRef<HTMLInputElement>(null);
    const renameInputRef = useRef<HTMLInputElement>(null);

    const rootFolders = folders.filter(f => !f.parent_folder_id);
    const childrenOf = (parentId: string) => folders.filter(f => f.parent_folder_id === parentId);

    // Group root folders into 3 zones
    const analysisResultFolders = rootFolders.filter(f => f.folder_type === "analysis_result");
    const analyzedFolders = rootFolders.filter(f =>
        f.folder_type !== "analysis_result" &&
        (f.analysis_status === "analyzed" || f.analysis_status === "stale" || f.analysis_status === "analyzing")
    );
    const notAnalyzedFolders = rootFolders.filter(f =>
        f.folder_type !== "analysis_result" &&
        (!f.analysis_status || f.analysis_status === "not_analyzed")
    );

    const toggleZone = (zone: string) => {
        setCollapsedZones(prev => ({ ...prev, [zone]: !prev[zone] }));
    };

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

    const renderAnalysisBadge = (status: AnalysisStatus | null | undefined) => {
        // Zone grouping communicates analyzed status; only show sub-status badges
        if (!status || status === "not_analyzed" || status === "analyzed") return null;
        const badgeMap: Record<string, { emoji: string; cls: string; label: string }> = {
            analyzing: { emoji: "⏳", cls: styles.badgeAnalyzing ?? "", label: "Analyzing…" },
            stale: { emoji: "⚠️", cls: styles.badgeStale ?? "", label: "Stale" },
        };
        const badge = badgeMap[status];
        if (!badge) return null;
        return <span className={`${styles.analysisBadge ?? ""} ${badge.cls}`} title={badge.label}>{badge.emoji}</span>;
    };

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
                        <>
                            <span className={styles.folderName} title={folder.name}>{folder.name}</span>
                            {renderAnalysisBadge(folder.analysis_status)}
                            {/* Inline shortcut icons (hover-reveal) */}
                            {(() => {
                                const isUserFolder = !folder.folder_type || folder.folder_type === "user";
                                if (isUserFolder && (!folder.analysis_status || folder.analysis_status === "not_analyzed") && onAnalyzeFolder) {
                                    return (
                                        <button
                                            className={styles.inlineIconBtn}
                                            onClick={e => { e.stopPropagation(); onAnalyzeFolder(folder.id); }}
                                            title={t("files.analyze", "Analyze")}
                                        >🔍</button>
                                    );
                                }
                                if ((folder.analysis_status === "analyzed" || folder.analysis_status === "stale") && onChatWithAnalysis) {
                                    return (
                                        <button
                                            className={styles.inlineIconBtn}
                                            onClick={e => { e.stopPropagation(); onChatWithAnalysis(folder.id); }}
                                            title={t("files.chatWithAnalysis", "Chat")}
                                        >💬</button>
                                    );
                                }
                                if (isUserFolder && folder.analysis_status === "stale" && onAnalyzeFolder) {
                                    return (
                                        <button
                                            className={styles.inlineIconBtn}
                                            onClick={e => { e.stopPropagation(); onAnalyzeFolder(folder.id); }}
                                            title={t("files.reanalyze", "Re-analyze")}
                                        >🔍</button>
                                    );
                                }
                                return null;
                            })()}
                        </>
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

    const renderZoneHeader = (zone: string, icon: string, label: string, count: number) => {
        const isCollapsed = collapsedZones[zone];
        return (
            <div
                className={styles.zoneHeader}
                onClick={() => toggleZone(zone)}
                title={isCollapsed ? t("files.expandZone", "Expand") : t("files.collapseZone", "Collapse")}
            >
                <span className={styles.zoneChevron}>{isCollapsed ? "▸" : "▾"}</span>
                <span className={styles.zoneIcon}>{icon}</span>
                <span className={styles.zoneLabel}>{label}</span>
                <span className={styles.zoneCount}>{count}</span>
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

            {/* Zone 1: Analysis Results */}
            {analysisResultFolders.length > 0 && (
                <div className={styles.zone}>
                    {renderZoneHeader("results", "📊", t("files.zoneAnalysisResults", "Analysis Results"), analysisResultFolders.length)}
                    {!collapsedZones["results"] && <div className={`${styles.zoneFolders} ${styles.zoneFoldersResults}`}>{analysisResultFolders.map(f => renderFolder(f, 0))}</div>}
                </div>
            )}

            {/* Zone 2: Analyzed */}
            {analyzedFolders.length > 0 && (
                <div className={styles.zone}>
                    {renderZoneHeader("analyzed", "✅", t("files.zoneAnalyzed", "Analyzed"), analyzedFolders.length)}
                    {!collapsedZones["analyzed"] && <div className={`${styles.zoneFolders} ${styles.zoneFoldersAnalyzed}`}>{analyzedFolders.map(f => renderFolder(f, 0))}</div>}
                </div>
            )}

            {/* Zone 3: Folders (Not Analyzed) */}
            {notAnalyzedFolders.length > 0 && (
                <div className={styles.zone}>
                    {renderZoneHeader("folders", "📁", t("files.zoneFolders", "Folders"), notAnalyzedFolders.length)}
                    {!collapsedZones["folders"] && <div className={`${styles.zoneFolders} ${styles.zoneFoldersNotAnalyzed}`}>{notAnalyzedFolders.map(f => renderFolder(f, 0))}</div>}
                </div>
            )}

            {creating && creating.parentId === null && renderCreateInput()}

            {/* Context menu */}
            {contextMenu && (
                <div
                    className={styles.contextMenu}
                    style={{ top: contextMenu.y, left: contextMenu.x }}
                >
                    {(() => {
                        const folder = folders.find(f => f.id === contextMenu.folderId);
                        const isUserFolder = !folder?.folder_type || folder.folder_type === "user";
                        const canAnalyze = isUserFolder && folder?.analysis_status !== "analyzing";
                        return (
                            <>
                                <button onClick={() => startRename(folder!)}>✏️ {t("files.rename")}</button>
                                <button onClick={() => {
                                    setCreating({ parentId: contextMenu.folderId });
                                    setNewFolderName("");
                                    setContextMenu(null);
                                }}>📁 {t("files.newSubfolder")}</button>
                                {canAnalyze && onAnalyzeFolder && (
                                    <button onClick={() => {
                                        onAnalyzeFolder(contextMenu.folderId);
                                        setContextMenu(null);
                                    }}>🔍 {t("files.analyze", "Analyze")}</button>
                                )}
                                {(folder?.analysis_status === "analyzed" || folder?.analysis_status === "stale" || folder?.folder_type === "analysis_result") && onChatWithAnalysis && (
                                    <button onClick={() => {
                                        onChatWithAnalysis(contextMenu.folderId);
                                        setContextMenu(null);
                                    }}>💬 {t("files.chatWithAnalysis", "Chat with analysis")}</button>
                                )}
                                {(folder?.analysis_status === "analyzed" || folder?.analysis_status === "stale") && onDeleteAnalysis && (
                                    <button
                                        className={styles.contextMenuDanger}
                                        onClick={() => {
                                            onDeleteAnalysis(contextMenu.folderId);
                                            setContextMenu(null);
                                        }}
                                    >🗑️ {t("files.deleteAnalysis", "Delete Analysis Data")}</button>
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
