/**
 * Folder Management API Layer
 *
 * Typed functions for backend folder CRUD operations
 * and document-folder assignment.
 */

import { getHeaders, fetchWithAuthRetry } from "./api";

// ======================== Types ========================

export type FolderType = "user" | "analysis_result";
export type AnalysisStatus = "not_analyzed" | "analyzing" | "analyzed" | "stale";

export interface Folder {
    id: string;
    name: string;
    group_id: string;
    parent_folder_id: string | null;
    folder_type: FolderType;
    analysis_status: AnalysisStatus | null;
    analysis_group_id: string | null;
    source_folder_id: string | null;
    analyzed_at: string | null;
    file_count: number | null;
    entity_count: number | null;
    community_count: number | null;
    created_at: string;
    updated_at: string;
}

export interface FolderCreate {
    name: string;
    parent_folder_id?: string | null;
    folder_type?: FolderType;
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

// ======================== Analysis ========================

export interface AnalyzeResult {
    status: string;
    folder_id: string;
    analysis_group_id: string;
    file_count: number;
    message: string;
}

export async function analyzeFolderApi(
    folderId: string,
    idToken: string
): Promise<AnalyzeResult> {
    const headers = await getHeaders(idToken);
    const response = await fetchWithAuthRetry(
        `/folders/${encodeURIComponent(folderId)}/analyze`,
        {
            method: "POST",
            headers,
        }
    );
    if (!response.ok) {
        let detail = response.statusText;
        try {
            const body = await response.json();
            detail = body.detail || detail;
        } catch {
            /* ignore */
        }
        throw new Error(detail);
    }
    return response.json();
}

export async function getFolderAnalysisStatusApi(
    folderId: string,
    idToken: string
): Promise<{ analysis_status: AnalysisStatus | null; file_count: number | null; entity_count: number | null; community_count: number | null }> {
    const response = await fetchWithAuthRetry(
        `/folders/${encodeURIComponent(folderId)}`,
        {
            method: "GET",
            headers: await getHeaders(idToken),
        }
    );
    if (!response.ok) {
        throw new Error(`Get folder status failed: ${response.statusText}`);
    }
    const folder: Folder = await response.json();
    return {
        analysis_status: folder.analysis_status,
        file_count: folder.file_count,
        entity_count: folder.entity_count,
        community_count: folder.community_count,
    };
}
