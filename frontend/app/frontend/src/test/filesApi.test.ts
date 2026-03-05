import { describe, it, expect, vi, beforeEach } from "vitest";
import {
    deleteFileApi,
    bulkDeleteFilesApi,
    listFilesApi,
    renameFileApi,
    moveFileApi,
    copyFileApi,
    getFileMetadataListApi,
    getFileMetadataApi,
    updateFileMetadataApi,
    lockFileApi,
    unlockFileApi
} from "../api/files";

// Mock getHeaders and fetchWithAuthRetry (delegates to globalThis.fetch so spies work)
vi.mock("../api/api", () => ({
    getHeaders: vi.fn(async () => ({ Authorization: "Bearer test-token" })),
    fetchWithAuthRetry: vi.fn((url: string, init: RequestInit) => globalThis.fetch(url, init))
}));

// Helper to set up a fetch mock for one call
function mockFetchOnce(body: unknown, status = 200, headers?: Record<string, string>) {
    const respHeaders = new Headers(headers);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(JSON.stringify(body), { status, statusText: status === 200 ? "OK" : "Error", headers: respHeaders })
    );
}

function mockFetchError(status: number, statusText: string) {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(null, { status, statusText })
    );
}

beforeEach(() => {
    vi.restoreAllMocks();
});

describe("deleteFileApi", () => {
    it("sends DELETE request and returns response", async () => {
        mockFetchOnce({ message: "deleted" });
        const result = await deleteFileApi("test.pdf", "token");
        expect(result.message).toBe("deleted");
        expect(globalThis.fetch).toHaveBeenCalledWith("/delete_uploaded", expect.objectContaining({ method: "POST" }));
    });

    it("throws on non-OK response", async () => {
        mockFetchError(500, "Internal Server Error");
        await expect(deleteFileApi("test.pdf", "token")).rejects.toThrow("Delete failed");
    });
});

describe("bulkDeleteFilesApi", () => {
    it("sends bulk delete with filenames array", async () => {
        mockFetchOnce({ message: "bulk deleted" });
        const result = await bulkDeleteFilesApi(["a.pdf", "b.pdf"], "token");
        expect(result.message).toBe("bulk deleted");
        const call = vi.mocked(globalThis.fetch).mock.calls[0];
        expect(JSON.parse(call[1]!.body as string)).toEqual({ filenames: ["a.pdf", "b.pdf"] });
    });
});

describe("listFilesApi", () => {
    it("returns array of filenames", async () => {
        mockFetchOnce(["file1.pdf", "file2.docx"]);
        const result = await listFilesApi("token");
        expect(result).toEqual(["file1.pdf", "file2.docx"]);
    });

    it("throws on failure", async () => {
        mockFetchError(403, "Forbidden");
        await expect(listFilesApi("token")).rejects.toThrow("List failed");
    });
});

describe("renameFileApi", () => {
    it("sends old and new filenames", async () => {
        mockFetchOnce({ message: "renamed" });
        await renameFileApi("old.pdf", "new.pdf", "token");
        const call = vi.mocked(globalThis.fetch).mock.calls[0];
        expect(JSON.parse(call[1]!.body as string)).toEqual({ old_filename: "old.pdf", new_filename: "new.pdf" });
    });
});

describe("moveFileApi", () => {
    it("sends filename and destination folder", async () => {
        mockFetchOnce({ message: "moved" });
        await moveFileApi("doc.pdf", "archive", "token", "inbox");
        const call = vi.mocked(globalThis.fetch).mock.calls[0];
        const body = JSON.parse(call[1]!.body as string);
        expect(body.filename).toBe("doc.pdf");
        expect(body.dest_folder).toBe("archive");
        expect(body.source_folder).toBe("inbox");
    });
});

describe("copyFileApi", () => {
    it("sends filename and destination filename", async () => {
        mockFetchOnce({ message: "copied" });
        await copyFileApi("doc.pdf", "doc_copy.pdf", "token");
        const call = vi.mocked(globalThis.fetch).mock.calls[0];
        const body = JSON.parse(call[1]!.body as string);
        expect(body.filename).toBe("doc.pdf");
        expect(body.dest_filename).toBe("doc_copy.pdf");
    });
});

describe("getFileMetadataListApi", () => {
    it("builds URL with query params", async () => {
        mockFetchOnce({ files: [], continuationToken: "abc" });
        await getFileMetadataListApi("token", "folder1", 10, "ct123");
        const url = vi.mocked(globalThis.fetch).mock.calls[0][0] as string;
        expect(url).toContain("folder_id=folder1");
        expect(url).toContain("page_size=10");
        expect(url).toContain("continuation_token=ct123");
    });

    it("omits query params when not provided", async () => {
        mockFetchOnce({ files: [] });
        await getFileMetadataListApi("token");
        const url = vi.mocked(globalThis.fetch).mock.calls[0][0] as string;
        expect(url).toBe("/file_metadata");
    });
});

describe("getFileMetadataApi", () => {
    it("encodes filename in URL and captures ETag", async () => {
        mockFetchOnce({ name: "my file.pdf", size: 1000 }, 200, { ETag: '"abc123"' });
        const result = await getFileMetadataApi("my file.pdf", "token");
        expect(result.name).toBe("my file.pdf");
        expect(result.etag).toBe('"abc123"');
        const url = vi.mocked(globalThis.fetch).mock.calls[0][0] as string;
        expect(url).toContain(encodeURIComponent("my file.pdf"));
    });
});

describe("updateFileMetadataApi", () => {
    it("sends If-Match header when etag provided", async () => {
        mockFetchOnce({ name: "doc.pdf" });
        await updateFileMetadataApi("doc.pdf", { tags: { a: "b" } }, '"etag1"', "token");
        const headers = vi.mocked(globalThis.fetch).mock.calls[0][1]!.headers as Record<string, string>;
        expect(headers["If-Match"]).toBe('"etag1"');
    });

    it("omits If-Match header when no etag", async () => {
        mockFetchOnce({ name: "doc.pdf" });
        await updateFileMetadataApi("doc.pdf", { tags: {} }, undefined, "token");
        const headers = vi.mocked(globalThis.fetch).mock.calls[0][1]!.headers as Record<string, string>;
        expect(headers["If-Match"]).toBeUndefined();
    });
});

describe("lockFileApi", () => {
    it("sends duration in body", async () => {
        mockFetchOnce({ message: "locked" });
        await lockFileApi("doc.pdf", 300, "token");
        const body = JSON.parse(vi.mocked(globalThis.fetch).mock.calls[0][1]!.body as string);
        expect(body.duration_seconds).toBe(300);
    });
});

describe("unlockFileApi", () => {
    it("uses DELETE method", async () => {
        mockFetchOnce({ message: "unlocked" });
        await unlockFileApi("doc.pdf", "token");
        expect(globalThis.fetch).toHaveBeenCalledWith(
            expect.stringContaining("/lock"),
            expect.objectContaining({ method: "DELETE" })
        );
    });
});
