/**
 * Files Page
 *
 * Modern file management UI with:
 * - Drag-and-drop upload zone
 * - File list with selection, sorting, context actions
 * - Bulk operations toolbar
 * - Rename dialog
 * - Responsive design
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { useMsal } from "@azure/msal-react";
import { useLogin, getToken } from "../../authConfig";
import {
    listFilesApi,
    uploadFilesApi,
    deleteFileApi,
    bulkDeleteFilesApi,
    renameFileApi,
    getFileIcon,
    ACCEPTED_FILE_TYPES,
} from "../../api/files";
import { UploadZone } from "../../components/FileManager/UploadZone";
import { FileList } from "../../components/FileManager/FileList";
import { FileToolbar } from "../../components/FileManager/FileToolbar";
import { RenameDialog } from "../../components/FileManager/RenameDialog";
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

    // State
    const [files, setFiles] = useState<string[]>([]);
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
        if (!client) return;
        try {
            setLoading(true);
            const token = await getToken(client);
            if (!token) throw new Error("Not authenticated");
            const result = await listFilesApi(token);
            setFiles(result);
        } catch (err: any) {
            addToast("error", `Failed to load files: ${err.message}`);
        } finally {
            setLoading(false);
        }
    }, [client, addToast]);

    useEffect(() => {
        loadFiles();
    }, [loadFiles]);

    // Upload handler
    const handleUpload = useCallback(
        async (fileList: File[]) => {
            if (!client || fileList.length === 0) return;
            try {
                setUploading(true);
                setUploadProgress(0);
                const token = await getToken(client);
                if (!token) throw new Error("Not authenticated");
                const result = await uploadFilesApi(fileList, token, (loaded, total) => {
                    setUploadProgress(Math.round((loaded / total) * 100));
                });
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
        [client, addToast, loadFiles]
    );

    // Delete handler
    const handleDelete = useCallback(
        async (filenames: string[]) => {
            if (!client) return;
            const confirmMsg = filenames.length === 1 ? `Delete "${filenames[0]}"?` : `Delete ${filenames.length} files?`;
            if (!window.confirm(confirmMsg)) return;

            try {
                const token = await getToken(client);
                if (!token) throw new Error("Not authenticated");
                if (filenames.length === 1) {
                    await deleteFileApi(filenames[0], token);
                } else {
                    await bulkDeleteFilesApi(filenames, token);
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
            if (!client) return;
            try {
                const token = await getToken(client);
                if (!token) throw new Error("Not authenticated");
                await renameFileApi(oldName, newName, token);
                addToast("success", `Renamed to "${newName}"`);
                setRenameFile(null);
                await loadFiles();
            } catch (err: any) {
                addToast("error", `Rename failed: ${err.message}`);
            }
        },
        [client, addToast, loadFiles]
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

    // Not logged in guard
    if (!useLogin) {
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

    return (
        <div className={styles.container}>
            {/* Upload zone (drag & drop) */}
            <UploadZone
                onUpload={handleUpload}
                uploading={uploading}
                progress={uploadProgress}
                acceptedTypes={ACCEPTED_FILE_TYPES}
            />

            {/* Toolbar: search, sort, bulk actions */}
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
                onRefresh={loadFiles}
            />

            {/* File list */}
            <FileList
                files={filteredFiles}
                selected={selected}
                loading={loading}
                onToggleSelect={toggleSelect}
                onDelete={(f) => handleDelete([f])}
                onRename={(f) => setRenameFile(f)}
            />

            {/* Rename dialog */}
            {renameFile && (
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
