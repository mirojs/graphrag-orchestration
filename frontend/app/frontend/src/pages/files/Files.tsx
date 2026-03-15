/**
 * Files Page
 *
 * Modern file management UI with:
 * - Folder sidebar with create/rename/delete
 * - Drag-and-drop upload zone
 * - File list with selection, sorting, context actions
 * - Bulk operations toolbar
 * - Rename dialog
 * - Analysis CTA + toolbar analyze button
 * - Responsive design
 */

import { useState, useEffect, useCallback, useRef, useContext } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useMsal } from "@azure/msal-react";
import { useLogin, requireLogin, getToken } from "../../authConfig";
import { LoginContext } from "../../loginContext";
import {
    listFilesApi,
    uploadFilesApi,
    deleteFileApi,
    bulkDeleteFilesApi,
    renameFileApi,
    moveFileApi,
    getFileIcon,
    ACCEPTED_FILE_TYPES,
} from "../../api/files";
import {
    listFoldersApi,
    createFolderApi,
    renameFolderApi,
    deleteFolderApi,
    analyzeFolderApi,
    deleteFolderAnalysisApi,
    cancelFolderAnalysisApi,
    getFolderFileCountApi,
    Folder,
    SubfolderCount,
} from "../../api/folders";
import { UploadZone } from "../../components/FileManager/UploadZone";
import { FileList } from "../../components/FileManager/FileList";
import { FileToolbar } from "../../components/FileManager/FileToolbar";
import { RenameDialog } from "../../components/FileManager/RenameDialog";
import { FolderSidebar } from "../../components/FileManager/FolderSidebar";
import { MoveToFolderDialog } from "../../components/FileManager/MoveToFolderDialog";
import { FilePreviewPanel } from "../../components/FileManager/FilePreviewPanel";
import { Toast } from "../../components/FileManager/Toast";
import styles from "./Files.module.css";

export interface ToastMessage {
    id: number;
    type: "success" | "error" | "info";
    text: string;
}

const Files = () => {
    // Auth
    const client = useLogin ? useMsal().instance : null;
    const { loggedIn } = useContext(LoginContext);
    const { t } = useTranslation();
    const navigate = useNavigate();
    const [files, setFiles] = useState<string[]>([]);
    const [folders, setFolders] = useState<Folder[]>([]);
    const [activeFolderId, setActiveFolderId] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [selected, setSelected] = useState<Set<string>>(new Set());
    const [sortBy, setSortBy] = useState<"name" | "ext">("name");
    const [sortAsc, setSortAsc] = useState(true);
    const [searchQuery, setSearchQuery] = useState("");
    const [uploading, setUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);
    const [analyzingFolderIds, setAnalyzingFolderIds] = useState<Set<string>>(new Set());
    const analyzingGuardRef = useRef<Set<string>>(new Set());
    const [uploadedCount, setUploadedCount] = useState(0);
    const [uploadTotal, setUploadTotal] = useState(0);
    const [renameFile, setRenameFile] = useState<string | null>(null);
    const [moveFile, setMoveFile] = useState<string | null>(null);
    const [previewFile, setPreviewFile] = useState<string | null>(null);
    const [toasts, setToasts] = useState<ToastMessage[]>([]);
    const [recursiveFileCount, setRecursiveFileCount] = useState<number | null>(null);
    const [subfolderCounts, setSubfolderCounts] = useState<SubfolderCount[]>([]);
    const toastIdRef = useRef(0);

    // Track active folder name/id via ref (avoids callback dependency on `folders` state)
    const activeFolderNameRef = useRef<string | undefined>(undefined);
    const activeFolderIdRef = useRef<string | null>(null);

    // Toast helper
    const addToast = useCallback((type: ToastMessage["type"], text: string) => {
        const id = ++toastIdRef.current;
        setToasts(prev => [...prev, { id, type, text }]);
        setTimeout(() => setToasts(prev => prev.filter(toast => toast.id !== id)), 4000);
    }, []);

    const dismissToast = useCallback((id: number) => {
        setToasts(prev => prev.filter(toast => toast.id !== id));
    }, []);

    // Load files
    const loadFiles = useCallback(async () => {
        try {
            setLoading(true);
            const token = client ? await getToken(client) : undefined;
            if (useLogin && !token) {
                setFiles([]);
                return;
            }
            const result = await listFilesApi(token as string, undefined, activeFolderIdRef.current ?? undefined);
            setFiles(result);
        } catch (err: any) {
            addToast("error", `Failed to load files: ${err.message}`);
        } finally {
            setLoading(false);
        }
    }, [client, addToast]);

    // Load folders
    const loadFolders = useCallback(async () => {
        try {
            const token = client ? await getToken(client) : undefined;
            if (useLogin && !token) {
                setFolders([]);
                return;
            }
            const result = await listFoldersApi(token as string);
            setFolders(result);
        } catch (err: any) {
            // Keep existing folders on poll failure — don't wipe UI state
            console.warn("[folders] poll failed, keeping stale data", err?.message);
        }
    }, [client]);

    useEffect(() => {
        loadFiles();
        loadFolders();
    }, [loadFiles, loadFolders]);

    // Re-fetch files when folder selection changes
    useEffect(() => {
        activeFolderNameRef.current = activeFolderId
            ? folders.find(f => f.id === activeFolderId)?.name
            : undefined;
        activeFolderIdRef.current = activeFolderId;
        loadFiles();
        setSelected(new Set());
        // Fetch recursive file count + subfolder breakdown
        setRecursiveFileCount(null);
        setSubfolderCounts([]);
        if (activeFolderId) {
            (async () => {
                try {
                    const token = client ? await getToken(client) : undefined;
                    if (!useLogin || token) {
                        const result = await getFolderFileCountApi(activeFolderId, token as string);
                        setRecursiveFileCount(result.count);
                        setSubfolderCounts(result.subfolders || []);
                    }
                } catch (err) {
                    console.warn("[file-count] failed to fetch recursive count", err);
                }
            })();
        }
    }, [activeFolderId]); // eslint-disable-line react-hooks/exhaustive-deps

    // Poll folders while any folder is "analyzing" (every 5s)
    useEffect(() => {
        const hasAnalyzing = folders.some(f => f.analysis_status === "analyzing");
        if (!hasAnalyzing) return;
        const interval = setInterval(() => {
            loadFolders();
        }, 5000);
        return () => clearInterval(interval);
    }, [folders, loadFolders]);

    // Upload handler — bounded-parallel uploads (max 3 concurrent)
    const handleUpload = useCallback(
        async (fileList: File[]) => {
            if (fileList.length === 0) return;
            const CONCURRENCY = 3;
            try {
                setUploading(true);
                setUploadProgress(0);
                setUploadedCount(0);
                setUploadTotal(fileList.length);
                const token = client ? await getToken(client) : undefined;
                if (useLogin && !token) throw new Error("Not authenticated");

                let completed = 0;
                let successCount = 0;
                const fileProgress = new Float32Array(fileList.length); // per-file 0..1

                const updateOverallProgress = () => {
                    const sum = fileProgress.reduce((a, b) => a + b, 0);
                    setUploadProgress(Math.round((sum / fileList.length) * 100));
                    setUploadedCount(completed);
                };

                const uploadOne = async (index: number) => {
                    try {
                        await uploadFilesApi([fileList[index]], token as string, (loaded, total) => {
                            fileProgress[index] = loaded / total;
                            updateOverallProgress();
                        }, activeFolderId ?? undefined);
                        fileProgress[index] = 1;
                        completed++;
                        successCount++;
                        updateOverallProgress();
                    } catch (err: any) {
                        fileProgress[index] = 1;
                        completed++;
                        updateOverallProgress();
                        addToast("error", t("files.uploadFailed", { message: `${fileList[index].name}: ${err.message}` }));
                    }
                };

                // Process files with bounded concurrency
                let nextIndex = 0;
                const runWorker = async () => {
                    while (nextIndex < fileList.length) {
                        const idx = nextIndex++;
                        await uploadOne(idx);
                    }
                };
                const workers = Array.from({ length: Math.min(CONCURRENCY, fileList.length) }, () => runWorker());
                await Promise.all(workers);

                setUploadProgress(100);
                if (successCount > 0) {
                    addToast("success", t("files.filesUploaded", { count: successCount }));
                }
                await loadFiles();
                setSelected(new Set());
            } catch (err: any) {
                addToast("error", t("files.uploadFailed", { message: err.message }));
            } finally {
                setUploading(false);
                setUploadProgress(0);
                setUploadedCount(0);
                setUploadTotal(0);
            }
        },
        [client, addToast, loadFiles, activeFolderId]
    );

    // Delete handler
    const handleDelete = useCallback(
        async (filenames: string[]) => {
            const confirmMsg = filenames.length === 1 ? t("files.deleteConfirmSingle", { filename: filenames[0] }) : t("files.deleteConfirmMultiple", { count: filenames.length });
            if (!window.confirm(confirmMsg)) return;

            try {
                const token = client ? await getToken(client) : undefined;
                if (useLogin && !token) throw new Error("Not authenticated");
                const folderName = activeFolderNameRef.current;
                if (filenames.length === 1) {
                    await deleteFileApi(filenames[0], token as string, folderName);
                } else {
                    await bulkDeleteFilesApi(filenames, token as string, folderName);
                }
                addToast("success", t("files.filesDeleted", { count: filenames.length }));
                await loadFiles();
                setSelected(prev => {
                    const next = new Set(prev);
                    filenames.forEach(f => next.delete(f));
                    return next;
                });
            } catch (err: any) {
                addToast("error", t("files.deleteFailed", { message: err.message }));
            }
        },
        [client, addToast, loadFiles]
    );

    // Rename handler
    const handleRename = useCallback(
        async (oldName: string, newName: string) => {
            try {
                const token = client ? await getToken(client) : undefined;
                if (useLogin && !token) throw new Error("Not authenticated");
                await renameFileApi(oldName, newName, token as string, activeFolderNameRef.current);
                addToast("success", t("files.renamedTo", { name: newName }));
                setRenameFile(null);
                await loadFiles();
            } catch (err: any) {
                addToast("error", t("files.renameFailed", { message: err.message }));
            }
        },
        [client, addToast, loadFiles]
    );

    // Folder handlers
    const handleCreateFolder = useCallback(
        async (name: string, parentId: string | null) => {
            try {
                const token = client ? await getToken(client) : undefined;
                if (useLogin && !token) throw new Error("Not authenticated");
                await createFolderApi({ name, parent_folder_id: parentId }, token as string);
                addToast("success", t("files.folderCreated", { name }));
                await loadFolders();
            } catch (err: any) {
                addToast("error", t("files.createFolderFailed", { message: err.message }));
            }
        },
        [client, addToast, loadFolders]
    );

    const handleRenameFolder = useCallback(
        async (folderId: string, newName: string) => {
            try {
                const token = client ? await getToken(client) : undefined;
                if (useLogin && !token) throw new Error("Not authenticated");
                await renameFolderApi(folderId, newName, token as string);
                addToast("success", t("files.folderRenamed", { name: newName }));
                await loadFolders();
            } catch (err: any) {
                addToast("error", t("files.renameFolderFailed", { message: err.message }));
            }
        },
        [client, addToast, loadFolders]
    );

    const handleDeleteFolder = useCallback(
        async (folderId: string) => {
            if (!window.confirm(t("files.deleteFolderConfirm"))) return;
            try {
                const token = client ? await getToken(client) : undefined;
                if (useLogin && !token) throw new Error("Not authenticated");
                await deleteFolderApi(folderId, token as string, true);
                addToast("success", t("files.folderDeleted"));
                if (activeFolderId === folderId) setActiveFolderId(null);
                await loadFolders();
            } catch (err: any) {
                addToast("error", t("files.deleteFolderFailed", { message: err.message }));
            }
        },
        [client, addToast, loadFolders, activeFolderId]
    );

    // Analyze a folder (trigger Neo4j indexing)
    const handleAnalyzeFolder = useCallback(
        async (folderId: string) => {
            // Use ref for double-click guard (immune to stale closures)
            if (analyzingGuardRef.current.has(folderId)) return;
            analyzingGuardRef.current.add(folderId);
            // Optimistic UI: immediately show "analyzing" state
            setAnalyzingFolderIds(prev => new Set(prev).add(folderId));
            setFolders(prev => prev.map(f =>
                f.id === folderId
                    ? { ...f, analysis_status: "analyzing" as const, analysis_error: null }
                    : f
            ));
            try {
                const token = client ? await getToken(client) : undefined;
                if (useLogin && !token) throw new Error("Not authenticated");
                await analyzeFolderApi(folderId, token as string);
                await loadFolders();
            } catch (err: any) {
                const msg = err.message || "";
                const isAlreadyRunning = msg.includes("already in progress");
                if (isAlreadyRunning) {
                    // 409: analysis IS running — keep showing "analyzing", just reload
                    await loadFolders();
                } else {
                    // Real failure — revert optimistic update
                    setFolders(prev => prev.map(f =>
                        f.id === folderId
                            ? { ...f, analysis_status: "not_analyzed" as const }
                            : f
                    ));
                    addToast("error", msg || "Analysis failed");
                }
            } finally {
                analyzingGuardRef.current.delete(folderId);
                setAnalyzingFolderIds(prev => {
                    const next = new Set(prev);
                    next.delete(folderId);
                    return next;
                });
            }
        },
        [client, addToast, loadFolders]
    );

    // Navigate to chat scoped to a folder's analysis group
    const handleChatWithAnalysis = useCallback(
        (folderId: string) => {
            const folder = folders.find(f => f.id === folderId);
            const groupId = folder?.analysis_group_id || folderId;
            navigate(`/?folder=${encodeURIComponent(groupId)}`);
        },
        [folders, navigate]
    );

    // Delete analysis data for a folder (keeps original files)
    const handleDeleteAnalysis = useCallback(
        async (folderId: string) => {
            if (!window.confirm(t("files.deleteAnalysisConfirm"))) return;
            try {
                const token = client ? await getToken(client) : undefined;
                if (useLogin && !token) throw new Error("Not authenticated");
                await deleteFolderAnalysisApi(folderId, token as string);
                addToast("success", t("files.analysisDeleted"));
                await loadFolders();
            } catch (err: any) {
                addToast("error", t("files.deleteAnalysisFailed", { message: err.message }));
            }
        },
        [client, addToast, loadFolders, t]
    );

    const handleCancelAnalysis = useCallback(
        async (folderId: string) => {
            if (!window.confirm("Cancel the in-progress analysis? You can re-analyze later.")) return;
            try {
                const token = client ? await getToken(client) : undefined;
                if (useLogin && !token) throw new Error("Not authenticated");
                await cancelFolderAnalysisApi(folderId, token as string);
                addToast("info", "Analysis cancelled");
                await loadFolders();
            } catch (err: any) {
                addToast("error", err.message || "Failed to cancel analysis");
            }
        },
        [client, addToast, loadFolders]
    );

    // Move file to folder
    const handleMoveFile = useCallback(
        async (filename: string, destFolderId: string | null) => {
            try {
                const token = client ? await getToken(client) : undefined;
                if (useLogin && !token) throw new Error("Not authenticated");
                const destFolder = destFolderId ? folders.find(f => f.id === destFolderId) : null;
                const destFolderName = destFolder?.name ?? undefined;
                const sourceFolder = activeFolderId ? folders.find(f => f.id === activeFolderId)?.name : undefined;
                await moveFileApi(filename, destFolderName ?? "", token as string, sourceFolder);
                addToast("success", t("files.fileMoved", { filename, folder: destFolderName || t("files.rootLevel") }));
                setMoveFile(null);
                await loadFiles();
            } catch (err: any) {
                addToast("error", t("files.moveFailed", { message: err.message }));
            }
        },
        [client, addToast, loadFiles, folders, activeFolderId]
    );

    // Selection helpers
    const toggleSelect = useCallback((filename: string) => {
        setSelected(prev => {
            const next = new Set(prev);
            if (next.has(filename)) next.delete(filename);
            else next.add(filename);
            return next;
        });
    }, []);

    const selectAll = useCallback(() => {
        setSelected(new Set(filteredFiles));
    }, [files, searchQuery, sortBy, sortAsc]);

    const selectNone = useCallback(() => setSelected(new Set()), []);

    // Filter & sort
    const filteredFiles = files
        .filter(f => !searchQuery || f.toLowerCase().includes(searchQuery.toLowerCase()))
        .sort((a, b) => {
            let cmp = 0;
            if (sortBy === "name") {
                cmp = a.localeCompare(b, undefined, { sensitivity: "base" });
            } else {
                const extA = a.split(".").pop() || "";
                const extB = b.split(".").pop() || "";
                cmp = extA.localeCompare(extB) || a.localeCompare(b, undefined, { sensitivity: "base" });
            }
            return sortAsc ? cmp : -cmp;
        });

    // Breadcrumb
    const activeFolder = folders.find(f => f.id === activeFolderId);
    const parentFolder = activeFolder?.parent_folder_id ? folders.find(f => f.id === activeFolder.parent_folder_id) : null;

    // Not logged in guard — only block when login is required and user hasn't signed in
    if (requireLogin && !loggedIn) {
        return (
            <div className={styles.container}>
                <div className={styles.emptyState}>
                    <span className={styles.emptyIcon}>🔒</span>
                    <h2>{t("files.signInRequired")}</h2>
                    <p>{t("files.signInToManage")}</p>
                </div>
            </div>
        );
    }

    return (
        <div className={styles.container}>
            {/* Upload zone (drag & drop) */}
            <UploadZone
                    onUpload={handleUpload}
                    uploading={uploading}
                    progress={uploadProgress}
                    acceptedTypes={ACCEPTED_FILE_TYPES}
                    uploadedCount={uploadedCount}
                    uploadTotal={uploadTotal}
                />

            <div className={styles.mainArea}>
                <FolderSidebar
                    folders={folders}
                    activeFolderId={activeFolderId}
                    onSelectFolder={setActiveFolderId}
                    onCreateFolder={handleCreateFolder}
                    onRenameFolder={handleRenameFolder}
                    onDeleteFolder={handleDeleteFolder}
                    onAnalyzeFolder={handleAnalyzeFolder}
                    onChatWithAnalysis={handleChatWithAnalysis}
                    onDeleteAnalysis={handleDeleteAnalysis}
                />

                <div className={styles.contentArea}>
                    {/* Breadcrumb */}
                    {activeFolderId && (
                        <div className={styles.breadcrumb}>
                            <button className={styles.breadcrumbLink} onClick={() => setActiveFolderId(null)}>
                                {t("files.allFiles")}
                            </button>
                            <span className={styles.breadcrumbSep}>›</span>
                            {parentFolder && (
                                <>
                                    <button
                                        className={styles.breadcrumbLink}
                                        onClick={() => setActiveFolderId(parentFolder.id)}
                                    >
                                        {parentFolder.name}
                                    </button>
                                    <span className={styles.breadcrumbSep}>›</span>
                                </>
                            )}
                            <span className={styles.breadcrumbCurrent}>{activeFolder?.name}</span>
                        </div>
                    )}

                    {/* Hero CTA — shown when folder is selected, has files (including in subfolders), and is not yet analyzed */}
                    {activeFolder
                        && (!activeFolder.analysis_status || activeFolder.analysis_status === "not_analyzed")
                        && (!activeFolder.folder_type || activeFolder.folder_type === "user")
                        && (recursiveFileCount != null ? recursiveFileCount > 0 : filteredFiles.length > 0) && (
                        <div className={styles.analysisCta}>
                            {activeFolder.analysis_error && (
                                <div className={styles.analysisErrorBanner}>
                                    <span className={styles.analysisErrorIcon}>❌</span>
                                    <span className={styles.analysisErrorText}>Previous analysis failed: {activeFolder.analysis_error}</span>
                                </div>
                            )}
                            <div className={styles.analysisCtaContent}>
                                <span className={styles.analysisCtaIcon}>📊</span>
                                <div className={styles.analysisCtaText}>
                                    <strong>{t("files.readyToAnalyze", { count: recursiveFileCount ?? filteredFiles.length, defaultValue: `Ready to analyze all documents in this folder` })}</strong>
                                    <span>{t("files.analysisExplainer", "Build a knowledge graph from your files to enable AI-powered question answering.")}</span>
                                </div>
                            </div>
                            <button
                                className={styles.analysisCtaBtn}
                                onClick={() => handleAnalyzeFolder(activeFolder.id)}
                                disabled={analyzingFolderIds.has(activeFolder.id)}
                            >
                                {analyzingFolderIds.has(activeFolder.id)
                                    ? "⏳ Starting…"
                                    : `🔍 ${t("files.analyzeNow", "Analyze Now")}`}
                            </button>
                        </div>
                    )}

                    {/* Analysis result summary — shown for analyzed/result folders */}
                    {activeFolder && (activeFolder.analysis_status === "analyzed" || activeFolder.analysis_status === "stale" || activeFolder.analysis_status === "analyzing" || activeFolder.folder_type === "analysis_result") && (
                        <div className={styles.analysisSummary}>
                            <div className={styles.analysisSummaryHeader}>
                                <span className={styles.analysisSummaryIcon}>
                                    {activeFolder.analysis_status === "analyzing" ? "⏳" : activeFolder.analysis_status === "stale" ? "⚠️" : "📊"}
                                </span>
                                <span className={styles.analysisSummaryTitle}>
                                    {activeFolder.analysis_status === "analyzing"
                                        ? t("files.analysisInProgress", "Analysis in progress…")
                                        : activeFolder.analysis_status === "stale"
                                            ? t("files.analysisStale", "Analysis is stale — files changed since last run")
                                            : t("files.analysisComplete", "Analysis Complete")}
                                </span>
                            </div>
                            {/* Analysis error banner */}
                            {activeFolder.analysis_error && (
                                <div className={styles.analysisErrorBanner}>
                                    <span className={styles.analysisErrorIcon}>❌</span>
                                    <span className={styles.analysisErrorText}>{activeFolder.analysis_error}</span>
                                </div>
                            )}
                            <div className={styles.analysisSummaryStats}>
                                {activeFolder.file_count != null && (
                                    <span className={styles.analysisStat}>📄 {activeFolder.file_count} files</span>
                                )}
                                {activeFolder.entity_count != null && (
                                    <span className={styles.analysisStat}>🔗 {activeFolder.entity_count} entities</span>
                                )}
                                {activeFolder.relationship_count != null && (
                                    <span className={styles.analysisStat}>↔️ {activeFolder.relationship_count} relationships</span>
                                )}
                                {activeFolder.community_count != null && (
                                    <span className={styles.analysisStat}>🏘️ {activeFolder.community_count} communities</span>
                                )}
                                {activeFolder.section_count != null && (
                                    <span className={styles.analysisStat}>📑 {activeFolder.section_count} sections</span>
                                )}
                                {activeFolder.sentence_count != null && (
                                    <span className={styles.analysisStat}>💬 {activeFolder.sentence_count} sentences</span>
                                )}
                                {activeFolder.analyzed_at && (
                                    <span className={styles.analysisStat}>🕐 {new Date(activeFolder.analyzed_at).toLocaleString()}</span>
                                )}
                            </div>
                            {(activeFolder.analysis_status === "analyzed" || activeFolder.analysis_status === "stale" || activeFolder.folder_type === "analysis_result") && (
                                <div className={styles.analysisActions}>
                                    <button
                                        className={styles.chatWithAnalysisBtn}
                                        onClick={() => handleChatWithAnalysis(activeFolder.id)}
                                    >
                                        💬 {t("files.chatWithAnalysis", "Chat with this analysis")}
                                    </button>
                                    <button
                                        className={styles.deleteAnalysisBtn}
                                        onClick={() => handleDeleteAnalysis(activeFolder.id)}
                                    >
                                        🗑️ {t("files.deleteAnalysis", "Delete Analysis Data")}
                                    </button>
                                </div>
                            )}
                            {(activeFolder.analysis_status === "analyzed" || activeFolder.analysis_status === "stale") && (
                                <p className={styles.storageReminder}>
                                    {t("files.storageReminder")}
                                </p>
                            )}
                            {activeFolder.analysis_status === "analyzing" && (
                                <>
                                    {activeFolder.analysis_files_total != null && activeFolder.analysis_files_total > 0 ? (
                                        <>
                                            <div className={styles.analysisProgressText}>
                                                {(activeFolder.analysis_files_processed ?? 0) === 0
                                                    ? `Analyzing ${activeFolder.analysis_files_total} files in parallel…`
                                                    : (activeFolder.analysis_files_processed ?? 0) >= activeFolder.analysis_files_total
                                                        ? "Building knowledge graph…"
                                                        : `Analyzed ${activeFolder.analysis_files_processed} of ${activeFolder.analysis_files_total} files…`}
                                            </div>
                                            <div className={styles.analysisProgressBar}>
                                                <div
                                                    className={(activeFolder.analysis_files_processed ?? 0) === 0
                                                        ? styles.analysisProgressFill
                                                        : styles.analysisProgressFillDeterminate}
                                                    style={(activeFolder.analysis_files_processed ?? 0) > 0
                                                        ? { width: `${Math.min(95, Math.round(((activeFolder.analysis_files_processed ?? 0) / activeFolder.analysis_files_total) * 100))}%` }
                                                        : undefined}
                                                />
                                            </div>
                                        </>
                                    ) : (
                                        <>
                                            <div className={styles.analysisProgressText}>Analyzing…</div>
                                            <div className={styles.analysisProgressBar}>
                                                <div className={styles.analysisProgressFill} />
                                            </div>
                                        </>
                                    )}
                                    <div className={styles.analysisActions}>
                                        <button
                                            className={styles.cancelAnalysisBtn}
                                            onClick={() => handleCancelAnalysis(activeFolder.id)}
                                        >
                                            ✖ {t("files.cancelAnalysis", "Cancel Analysis")}
                                        </button>
                                    </div>
                                </>
                            )}
                        </div>
                    )}

                    {/* Toolbar: search, sort, bulk actions, analyze */}
                    <FileToolbar
                        fileCount={filteredFiles.length}
                        selectedCount={selected.size}
                        searchQuery={searchQuery}
                        onSearchChange={setSearchQuery}
                        sortBy={sortBy}
                        sortAsc={sortAsc}
                        onSortChange={(by) => {
                            if (by === sortBy) setSortAsc(!sortAsc);
                            else { setSortBy(by); setSortAsc(true); }
                        }}
                        onSelectAll={selectAll}
                        onSelectNone={selectNone}
                        onDeleteSelected={() => handleDelete(Array.from(selected))}
                        onRefresh={() => { loadFiles(); loadFolders(); }}
                        activeFolderId={activeFolderId}
                        analysisStatus={activeFolder?.analysis_status}
                        isUserFolder={!activeFolder?.folder_type || activeFolder.folder_type === "user"}
                        onAnalyzeFolder={activeFolderId ? () => handleAnalyzeFolder(activeFolderId) : undefined}
                    />

                    {/* File list */}
                    <FileList
                        files={filteredFiles}
                        selected={selected}
                        loading={loading}
                        onToggleSelect={toggleSelect}
                        onDelete={(f) => handleDelete([f])}
                        onRename={(f) => setRenameFile(f)}
                        onMove={(f) => setMoveFile(f)}
                        onPreview={(f) => setPreviewFile(f)}
                        subfolderCounts={subfolderCounts}
                    />
                </div>

                {/* File preview side panel */}
                {previewFile && (
                    <FilePreviewPanel
                        filename={previewFile}
                        allFiles={filteredFiles}
                        folder={activeFolder?.name}
                        onDismiss={() => setPreviewFile(null)}
                        onNavigate={(f) => setPreviewFile(f)}
                    />
                )}
            </div>

            {/* Rename dialog */}
            {renameFile && (
                <RenameDialog
                    currentName={renameFile}
                    onRename={(newName) => handleRename(renameFile, newName)}
                    onDismiss={() => setRenameFile(null)}
                />
            )}

            {/* Move to folder dialog */}
            {moveFile && (
                <MoveToFolderDialog
                    filename={moveFile}
                    folders={folders}
                    currentFolderId={activeFolderId}
                    onMove={handleMoveFile}
                    onDismiss={() => setMoveFile(null)}
                />
            )}

            {/* Toast notifications */}
            <div className={styles.toastContainer}>
                {toasts.map(toast => (
                    <Toast key={toast.id} type={toast.type} text={toast.text} onDismiss={() => dismissToast(toast.id)} />
                ))}
            </div>
        </div>
    );
};

export default Files;
