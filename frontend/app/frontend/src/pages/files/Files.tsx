/**
 * Files Page
 *
 * Modern file management UI with:
 * - Folder sidebar with create/rename/delete
 * - Drag-and-drop upload zone
 * - File list with selection, sorting, context actions
 * - Bulk operations toolbar
 * - Rename dialog
 * - Shared Library tab (graceful when unconfigured)
 * - Responsive design
 */

import { useState, useEffect, useCallback, useRef, useContext } from "react";
import { useMsal } from "@azure/msal-react";
import { useLogin, requireLogin, getToken } from "../../authConfig";
import { LoginContext } from "../../loginContext";
import {
    listFilesApi,
    listGlobalFilesApi,
    uploadFilesApi,
    deleteFileApi,
    bulkDeleteFilesApi,
    renameFileApi,
    getFileIcon,
    ACCEPTED_FILE_TYPES,
} from "../../api/files";
import {
    listFoldersApi,
    createFolderApi,
    renameFolderApi,
    deleteFolderApi,
    Folder,
} from "../../api/folders";
import { UploadZone } from "../../components/FileManager/UploadZone";
import { FileList } from "../../components/FileManager/FileList";
import { FileToolbar } from "../../components/FileManager/FileToolbar";
import { RenameDialog } from "../../components/FileManager/RenameDialog";
import { FolderSidebar } from "../../components/FileManager/FolderSidebar";
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

    // State
    const [activeTab, setActiveTab] = useState<"my" | "shared">("my");
    const [files, setFiles] = useState<string[]>([]);
    const [globalFiles, setGlobalFiles] = useState<string[]>([]);
    const [sharedAvailable, setSharedAvailable] = useState(true);
    const [folders, setFolders] = useState<Folder[]>([]);
    const [activeFolderId, setActiveFolderId] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [selected, setSelected] = useState<Set<string>>(new Set());
    const [sortBy, setSortBy] = useState<"name" | "ext">("name");
    const [sortAsc, setSortAsc] = useState(true);
    const [searchQuery, setSearchQuery] = useState("");
    const [uploading, setUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);
    const [renameFile, setRenameFile] = useState<string | null>(null);
    const [toasts, setToasts] = useState<ToastMessage[]>([]);
    const toastIdRef = useRef(0);

    // Toast helper
    const addToast = useCallback((type: ToastMessage["type"], text: string) => {
        const id = ++toastIdRef.current;
        setToasts(prev => [...prev, { id, type, text }]);
        setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000);
    }, []);

    const dismissToast = useCallback((id: number) => {
        setToasts(prev => prev.filter(t => t.id !== id));
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
            const result = await listFilesApi(token as string);
            setFiles(result);
        } catch (err: any) {
            addToast("error", `Failed to load files: ${err.message}`);
        } finally {
            setLoading(false);
        }
    }, [client, addToast]);

    const loadGlobalFiles = useCallback(async () => {
        try {
            setLoading(true);
            const result = await listGlobalFilesApi();
            setGlobalFiles(result);
            setSharedAvailable(true);
        } catch (err: any) {
            setGlobalFiles([]);
            setSharedAvailable(false);
        } finally {
            setLoading(false);
        }
    }, []);

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
            // Folders API may not be available — degrade silently
            setFolders([]);
        }
    }, [client]);

    useEffect(() => {
        loadFiles();
        loadFolders();
    }, [loadFiles, loadFolders]);

    useEffect(() => {
        if (activeTab === "shared") {
            loadGlobalFiles();
        }
    }, [activeTab, loadGlobalFiles]);

    // Upload handler
    const handleUpload = useCallback(
        async (fileList: File[]) => {
            if (fileList.length === 0) return;
            try {
                setUploading(true);
                setUploadProgress(0);
                const token = client ? await getToken(client) : undefined;
                if (useLogin && !token) throw new Error("Not authenticated");
                const result = await uploadFilesApi(fileList, token as string, (loaded, total) => {
                    setUploadProgress(Math.round((loaded / total) * 100));
                }, activeFolderId ?? undefined);
                addToast("success", result.message || `${fileList.length} file(s) uploaded`);
                await loadFiles();
                setSelected(new Set());
            } catch (err: any) {
                addToast("error", `Upload failed: ${err.message}`);
            } finally {
                setUploading(false);
                setUploadProgress(0);
            }
        },
        [client, addToast, loadFiles, activeFolderId]
    );

    // Delete handler
    const handleDelete = useCallback(
        async (filenames: string[]) => {
            const confirmMsg = filenames.length === 1 ? `Delete "${filenames[0]}"?` : `Delete ${filenames.length} files?`;
            if (!window.confirm(confirmMsg)) return;

            try {
                const token = client ? await getToken(client) : undefined;
                if (useLogin && !token) throw new Error("Not authenticated");
                if (filenames.length === 1) {
                    await deleteFileApi(filenames[0], token as string);
                } else {
                    await bulkDeleteFilesApi(filenames, token as string);
                }
                addToast("success", `${filenames.length} file(s) deleted`);
                await loadFiles();
                setSelected(prev => {
                    const next = new Set(prev);
                    filenames.forEach(f => next.delete(f));
                    return next;
                });
            } catch (err: any) {
                addToast("error", `Delete failed: ${err.message}`);
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
                await renameFileApi(oldName, newName, token as string);
                addToast("success", `Renamed to "${newName}"`);
                setRenameFile(null);
                await loadFiles();
            } catch (err: any) {
                addToast("error", `Rename failed: ${err.message}`);
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
                addToast("success", `Folder "${name}" created`);
                await loadFolders();
            } catch (err: any) {
                addToast("error", `Create folder failed: ${err.message}`);
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
                addToast("success", `Folder renamed to "${newName}"`);
                await loadFolders();
            } catch (err: any) {
                addToast("error", `Rename folder failed: ${err.message}`);
            }
        },
        [client, addToast, loadFolders]
    );

    const handleDeleteFolder = useCallback(
        async (folderId: string) => {
            if (!window.confirm("Delete this folder? Files inside will be moved to All Files.")) return;
            try {
                const token = client ? await getToken(client) : undefined;
                if (useLogin && !token) throw new Error("Not authenticated");
                await deleteFolderApi(folderId, token as string, true);
                addToast("success", "Folder deleted");
                if (activeFolderId === folderId) setActiveFolderId(null);
                await loadFolders();
            } catch (err: any) {
                addToast("error", `Delete folder failed: ${err.message}`);
            }
        },
        [client, addToast, loadFolders, activeFolderId]
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
    const activeFiles = activeTab === "my" ? files : globalFiles;
    const filteredFiles = activeFiles
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
                    <h2>Sign in Required</h2>
                    <p>Please sign in to manage your files.</p>
                </div>
            </div>
        );
    }

    const isShared = activeTab === "shared";

    return (
        <div className={styles.container}>
            {/* Tab bar */}
            <div className={styles.tabBar}>
                <button
                    className={`${styles.tab} ${activeTab === "my" ? styles.tabActive : ""}`}
                    onClick={() => setActiveTab("my")}
                >
                    My Files
                </button>
                {sharedAvailable && (
                    <button
                        className={`${styles.tab} ${activeTab === "shared" ? styles.tabActive : ""}`}
                        onClick={() => setActiveTab("shared")}
                    >
                        Shared Library
                    </button>
                )}
            </div>

            {/* Upload zone (drag & drop) — only for My Files */}
            {!isShared && (
                <UploadZone
                    onUpload={handleUpload}
                    uploading={uploading}
                    progress={uploadProgress}
                    acceptedTypes={ACCEPTED_FILE_TYPES}
                />
            )}

            <div className={styles.mainArea}>
                {/* Folder sidebar — only for My Files */}
                {!isShared && (
                    <FolderSidebar
                        folders={folders}
                        activeFolderId={activeFolderId}
                        onSelectFolder={setActiveFolderId}
                        onCreateFolder={handleCreateFolder}
                        onRenameFolder={handleRenameFolder}
                        onDeleteFolder={handleDeleteFolder}
                    />
                )}

                <div className={styles.contentArea}>
                    {/* Breadcrumb */}
                    {!isShared && activeFolderId && (
                        <div className={styles.breadcrumb}>
                            <button className={styles.breadcrumbLink} onClick={() => setActiveFolderId(null)}>
                                All Files
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

                    {/* Toolbar: search, sort, bulk actions */}
                    <FileToolbar
                        fileCount={filteredFiles.length}
                        selectedCount={isShared ? 0 : selected.size}
                        searchQuery={searchQuery}
                        onSearchChange={setSearchQuery}
                        sortBy={sortBy}
                        sortAsc={sortAsc}
                        onSortChange={(by) => {
                            if (by === sortBy) setSortAsc(!sortAsc);
                            else { setSortBy(by); setSortAsc(true); }
                        }}
                        onSelectAll={isShared ? () => {} : selectAll}
                        onSelectNone={isShared ? () => {} : selectNone}
                        onDeleteSelected={isShared ? () => {} : () => handleDelete(Array.from(selected))}
                        onRefresh={isShared ? loadGlobalFiles : () => { loadFiles(); loadFolders(); }}
                    />

                    {/* File list */}
                    <FileList
                        files={filteredFiles}
                        selected={isShared ? new Set<string>() : selected}
                        loading={loading}
                        onToggleSelect={isShared ? () => {} : toggleSelect}
                        onDelete={isShared ? () => {} : (f) => handleDelete([f])}
                        onRename={isShared ? () => {} : (f) => setRenameFile(f)}
                    />
                </div>
            </div>

            {/* Rename dialog — only for My Files */}
            {!isShared && renameFile && (
                <RenameDialog
                    currentName={renameFile}
                    onRename={(newName) => handleRename(renameFile, newName)}
                    onDismiss={() => setRenameFile(null)}
                />
            )}

            {/* Toast notifications */}
            <div className={styles.toastContainer}>
                {toasts.map(t => (
                    <Toast key={t.id} type={t.type} text={t.text} onDismiss={() => dismissToast(t.id)} />
                ))}
            </div>
        </div>
    );
};

export default Files;
