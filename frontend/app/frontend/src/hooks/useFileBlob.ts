import { useCallback, useEffect, useRef, useState } from "react";
import { useMsal } from "@azure/msal-react";
import { useLogin, getToken } from "../authConfig";
import { getHeaders } from "../api/api";
import { getFileContentUrl } from "../api/files";

interface FileBlobState {
    blobUrl: string | null;
    contentType: string | null;
    rawBytes: ArrayBuffer | null;
    loading: boolean;
    error: string | null;
}

export function useFileBlob(filename: string | null, folder?: string) {
    const client = useLogin ? useMsal().instance : undefined;
    const [state, setState] = useState<FileBlobState>({
        blobUrl: null,
        contentType: null,
        rawBytes: null,
        loading: false,
        error: null,
    });
    const prevBlobUrl = useRef<string | null>(null);

    const fetchFile = useCallback(async (name: string) => {
        setState({ blobUrl: null, contentType: null, rawBytes: null, loading: true, error: null });

        try {
            const token = client ? await getToken(client) : undefined;
            const headers = await getHeaders(token);
            const url = getFileContentUrl(name, folder);
            const resp = await fetch(url, { headers });

            if (!resp.ok) {
                throw new Error(`Failed to load file (${resp.status})`);
            }

            const ct = resp.headers.get("content-type") || "application/octet-stream";
            const buf = await resp.arrayBuffer();
            const blob = new Blob([buf], { type: ct });
            const blobUrl = URL.createObjectURL(blob);

            if (prevBlobUrl.current) {
                URL.revokeObjectURL(prevBlobUrl.current);
            }
            prevBlobUrl.current = blobUrl;

            setState({ blobUrl, contentType: ct, rawBytes: buf, loading: false, error: null });
        } catch (err: any) {
            setState({ blobUrl: null, contentType: null, rawBytes: null, loading: false, error: err.message || "Unknown error" });
        }
    }, [client, folder]);

    useEffect(() => {
        if (filename) {
            fetchFile(filename);
        } else {
            if (prevBlobUrl.current) {
                URL.revokeObjectURL(prevBlobUrl.current);
                prevBlobUrl.current = null;
            }
            setState({ blobUrl: null, contentType: null, rawBytes: null, loading: false, error: null });
        }
    }, [filename, fetchFile]);

    // Cleanup on unmount
    useEffect(() => {
        return () => {
            if (prevBlobUrl.current) {
                URL.revokeObjectURL(prevBlobUrl.current);
            }
        };
    }, []);

    return state;
}
