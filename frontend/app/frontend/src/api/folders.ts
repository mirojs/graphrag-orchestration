/**
 * Folder Management API Layer
 *
 * Typed functions for backend folder CRUD operations
 * and document-folder assignment.
 */

import { getHeaders, fetchWithAuthRetry } from "./api";

// ======================== Types ========================

export interface Folder {
    id: string;
    name: string;
    group_id: string;
    parent_folder_id: string | null;
    created_at: string;
    updated_at: string;
}

export interface FolderCreate {
    name: string;
    parent_folder_id?: string | null;
}

// ======================== CRUD ========================

export async function listFoldersApi(
    idToken: string,
    parentFolderId?: string
): Promise<Folder[]> {
    const params = parentFolderId ? `?parent_folder_id=${encodeURIComponent(parentFolderId)}` : "";
    const response = await fetchWithAuthRetry(`/folders${params}`, {
        method: "GET",
        headers: await getHeaders(idToken),
    });
    if (!response.ok) {
        throw new Error(`List folders failed: ${response.statusText}`);
    }
    return response.json();
}

export async function createFolderApi(
    folder: FolderCreate,
    idToken: string
): Promise<Folder> {
    const headers = await getHeaders(idToken);
    const response = await fetchWithAuthRetry("/folders", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(folder),
    });
    if (!response.ok) {
        let detail = response.statusText;
        try {
            const body = await response.json();
            detail = body.detail || detail;
        } catch { /* ignore */ }
        throw new Error(detail);
    }
    return response.json();
}

export async function renameFolderApi(
    folderId: string,
    newName: string,
    idToken: string
): Promise<Folder> {
    const headers = await getHeaders(idToken);
    const response = await fetchWithAuthRetry(`/folders/${encodeURIComponent(folderId)}`, {
        method: "PUT",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName }),
    });
    if (!response.ok) {
        let detail = response.statusText;
        try {
            const body = await response.json();
            detail = body.detail || detail;
        } catch { /* ignore */ }
        throw new Error(detail);
    }
    return response.json();
}

export async function deleteFolderApi(
    folderId: string,
    idToken: string,
    cascade = false
): Promise<{ status: string; folder_id: string }> {
    const params = cascade ? "?cascade=true" : "";
    const response = await fetchWithAuthRetry(`/folders/${encodeURIComponent(folderId)}${params}`, {
        method: "DELETE",
        headers: await getHeaders(idToken),
    });
    if (!response.ok) {
        let detail = response.statusText;
        try {
            const body = await response.json();
            detail = body.detail || detail;
        } catch { /* ignore */ }
        throw new Error(detail);
    }
    return response.json();
}

// ======================== Document Assignment ========================

export async function assignDocumentToFolderApi(
    folderId: string,
    documentId: string,
    idToken: string
): Promise<{ status: string }> {
    const headers = await getHeaders(idToken);
    const response = await fetchWithAuthRetry(`/folders/${encodeURIComponent(folderId)}/documents`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ document_id: documentId }),
    });
    if (!response.ok) {
        throw new Error(`Assign to folder failed: ${response.statusText}`);
    }
    return response.json();
}

export async function unassignDocumentFromFolderApi(
    folderId: string,
    documentId: string,
    idToken: string
): Promise<{ status: string }> {
    const response = await fetchWithAuthRetry(
        `/folders/${encodeURIComponent(folderId)}/documents/${encodeURIComponent(documentId)}`,
        {
            method: "DELETE",
            headers: await getHeaders(idToken),
        }
    );
    if (!response.ok) {
        throw new Error(`Unassign from folder failed: ${response.statusText}`);
    }
    return response.json();
}
