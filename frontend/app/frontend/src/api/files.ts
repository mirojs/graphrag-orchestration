/**
 * File Management API Layer
 *
 * Typed functions for all backend file operations:
 * upload, delete, bulk-delete, rename, move, copy, list, metadata, lock/unlock.
 */

import { getHeaders, fetchWithAuthRetry } from "./api";

// ======================== Types ========================

export interface FileItem {
    name: string;
    /** Full blob path (user_id/filename) — returned by some endpoints */
    path?: string;
    /** Size in bytes */
    size?: number;
    /** MIME type */
    contentType?: string;
    /** ISO timestamp */
    lastModified?: string;
    /** Folder grouping ID */
    folderId?: string;
    /** User-defined tags */
    tags?: Record<string, string>;
    /** Additional properties */
    properties?: Record<string, string>;
    /** ETag for concurrency control */
    etag?: string;
    /** Lock holder OID */
    lockedBy?: string;
    /** Lock expiry ISO timestamp */
    lockExpires?: string;
}

export interface FileUploadResult {
    filename: string;
    status: "success" | "failed";
    error?: string;
}

export interface FileOperationResponse {
    message: string;
    results?: FileUploadResult[];
}

export interface FileMetadataListResponse {
    files: FileItem[];
    continuationToken?: string;
}

// ======================== Upload ========================

export async function uploadFilesApi(
    files: File[],
    idToken: string,
    onProgress?: (loaded: number, total: number) => void,
    folderId?: string
): Promise<FileOperationResponse> {
    const formData = new FormData();
    for (const file of files) {
        formData.append("file", file);
    }
    if (folderId) {
        formData.append("folder_id", folderId);
    }

    // Use XMLHttpRequest for progress tracking if callback provided
    if (onProgress) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open("POST", "/upload");

            // Set auth header
            if (idToken) {
                xhr.setRequestHeader("Authorization", `Bearer ${idToken}`);
            }

            xhr.upload.onprogress = (e) => {
                if (e.lengthComputable) {
                    onProgress(e.loaded, e.total);
                }
            };

            xhr.onload = () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve(JSON.parse(xhr.responseText));
                } else {
                    reject(new Error(`Upload failed: ${xhr.statusText}`));
                }
            };

            xhr.onerror = () => reject(new Error("Upload failed"));
            xhr.send(formData);
        });
    }

    const response = await fetchWithAuthRetry("/upload", {
        method: "POST",
        headers: await getHeaders(idToken),
        body: formData,
    });
    if (!response.ok) {
        throw new Error(`Upload failed: ${response.statusText}`);
    }
    return response.json();
}

// ======================== Delete ========================

export async function deleteFileApi(filename: string, idToken: string, folder?: string): Promise<FileOperationResponse> {
    const headers = await getHeaders(idToken);
    const response = await fetchWithAuthRetry("/delete_uploaded", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ filename, ...(folder ? { folder } : {}) }),
    });
    if (!response.ok) throw new Error(`Delete failed: ${response.statusText}`);
    return response.json();
}

export async function bulkDeleteFilesApi(filenames: string[], idToken: string, folder?: string): Promise<FileOperationResponse> {
    const headers = await getHeaders(idToken);
    const response = await fetchWithAuthRetry("/delete_uploaded_bulk", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ filenames, ...(folder ? { folder } : {}) }),
    });
    if (!response.ok) throw new Error(`Bulk delete failed: ${response.statusText}`);
    return response.json();
}

// ======================== List ========================

export async function listFilesApi(idToken: string, folder?: string, folderId?: string): Promise<string[]> {
    const searchParams = new URLSearchParams();
    if (folderId) searchParams.set("folder_id", folderId);
    else if (folder) searchParams.set("folder", folder);
    const qs = searchParams.toString();
    const response = await fetchWithAuthRetry(`/list_uploaded${qs ? `?${qs}` : ""}`, {
        method: "GET",
        headers: await getHeaders(idToken),
    });
    if (!response.ok) {
        let detail = "";
        try {
            const body = await response.json();
            detail = body.detail || body.message || JSON.stringify(body);
        } catch {
            detail = response.statusText || `HTTP ${response.status}`;
        }
        throw new Error(`List failed (${response.status}): ${detail}`);
    }
    return response.json();
}

// ======================== Rename / Move / Copy ========================

export async function renameFileApi(
    oldFilename: string,
    newFilename: string,
    idToken: string,
    folder?: string
): Promise<FileOperationResponse> {
    const headers = await getHeaders(idToken);
    const response = await fetchWithAuthRetry("/rename_uploaded", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ old_filename: oldFilename, new_filename: newFilename, ...(folder ? { folder } : {}) }),
    });
    if (!response.ok) throw new Error(`Rename failed: ${response.statusText}`);
    return response.json();
}

export async function moveFileApi(
    filename: string,
    destFolder: string,
    idToken: string,
    sourceFolder?: string
): Promise<FileOperationResponse> {
    const headers = await getHeaders(idToken);
    const response = await fetchWithAuthRetry("/move_uploaded", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ filename, source_folder: sourceFolder, dest_folder: destFolder }),
    });
    if (!response.ok) throw new Error(`Move failed: ${response.statusText}`);
    return response.json();
}

export async function copyFileApi(
    filename: string,
    destFilename: string,
    idToken: string
): Promise<FileOperationResponse> {
    const headers = await getHeaders(idToken);
    const response = await fetchWithAuthRetry("/copy_uploaded", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ filename, dest_filename: destFilename }),
    });
    if (!response.ok) throw new Error(`Copy failed: ${response.statusText}`);
    return response.json();
}

// ======================== Metadata ========================

export async function getFileMetadataListApi(
    idToken: string,
    folderId?: string,
    pageSize?: number,
    continuationToken?: string
): Promise<FileMetadataListResponse> {
    const params = new URLSearchParams();
    if (folderId) params.set("folder_id", folderId);
    if (pageSize) params.set("page_size", String(pageSize));
    if (continuationToken) params.set("continuation_token", continuationToken);

    const url = `/file_metadata${params.toString() ? "?" + params.toString() : ""}`;
    const response = await fetchWithAuthRetry(url, {
        method: "GET",
        headers: await getHeaders(idToken),
    });
    if (!response.ok) throw new Error(`Metadata list failed: ${response.statusText}`);
    return response.json();
}

export async function getFileMetadataApi(filename: string, idToken: string): Promise<FileItem> {
    const response = await fetchWithAuthRetry(`/file_metadata/${encodeURIComponent(filename)}`, {
        method: "GET",
        headers: await getHeaders(idToken),
    });
    if (!response.ok) throw new Error(`Metadata fetch failed: ${response.statusText}`);
    const data = await response.json();
    // Capture ETag from response header
    data.etag = response.headers.get("ETag") || undefined;
    return data;
}

export async function updateFileMetadataApi(
    filename: string,
    updates: { tags?: Record<string, string>; properties?: Record<string, string>; folder_id?: string },
    etag: string | undefined,
    idToken: string
): Promise<FileItem> {
    const headers: Record<string, string> = {
        ...(await getHeaders(idToken)),
        "Content-Type": "application/json",
    };
    if (etag) {
        headers["If-Match"] = etag;
    }
    const response = await fetchWithAuthRetry(`/file_metadata/${encodeURIComponent(filename)}`, {
        method: "PUT",
        headers,
        body: JSON.stringify(updates),
    });
    if (!response.ok) throw new Error(`Metadata update failed: ${response.statusText}`);
    return response.json();
}

// ======================== Locking ========================

export async function lockFileApi(
    filename: string,
    durationSeconds: number,
    idToken: string
): Promise<{ message: string }> {
    const headers = await getHeaders(idToken);
    const response = await fetchWithAuthRetry(`/file_metadata/${encodeURIComponent(filename)}/lock`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ duration_seconds: durationSeconds }),
    });
    if (!response.ok) throw new Error(`Lock failed: ${response.statusText}`);
    return response.json();
}

export async function unlockFileApi(filename: string, idToken: string): Promise<{ message: string }> {
    const response = await fetchWithAuthRetry(`/file_metadata/${encodeURIComponent(filename)}/lock`, {
        method: "DELETE",
        headers: await getHeaders(idToken),
    });
    if (!response.ok) throw new Error(`Unlock failed: ${response.statusText}`);
    return response.json();
}

// ======================== Content / Preview ========================

export function getFileContentUrl(path: string, folder?: string): string {
    const base = `/content/${encodeURIComponent(path)}`;
    return folder ? `${base}?folder=${encodeURIComponent(folder)}` : base;
}

// ======================== Helpers ========================

const FILE_ICONS: Record<string, string> = {
    pdf: "📄",
    docx: "📝",
    xlsx: "📊",
    pptx: "📰",
    txt: "📃",
    md: "📃",
    json: "🔧",
    html: "🌐",
    png: "🖼️",
    jpg: "🖼️",
    jpeg: "🖼️",
    bmp: "🖼️",
    svg: "🖼️",
    tiff: "🖼️",
    heic: "🖼️",
};

export function getFileIcon(filename: string): string {
    const ext = filename.split(".").pop()?.toLowerCase() || "";
    return FILE_ICONS[ext] || "📎";
}

export function formatFileSize(bytes: number | undefined): string {
    if (bytes === undefined || bytes === null) return "—";
    if (bytes === 0) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function getFileExtension(filename: string): string {
    return filename.split(".").pop()?.toLowerCase() || "";
}

export const ACCEPTED_FILE_TYPES = ".txt,.csv,.png,.jpg,.jpeg,.bmp,.tiff,.pdf,.docx,.xlsx,.pptx,.html,.htm";
