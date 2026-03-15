import { describe, it, expect } from "vitest";
import { getFileIcon, formatFileSize, getFileExtension, getFileContentUrl } from "../api/files";

describe("getFileIcon", () => {
    it("returns PDF icon for .pdf", () => {
        expect(getFileIcon("report.pdf")).toBe("📄");
    });

    it("returns spreadsheet icon for .xlsx", () => {
        expect(getFileIcon("data.xlsx")).toBe("📊");
    });

    it("returns image icon for image extensions", () => {
        for (const ext of ["png", "jpg", "jpeg", "bmp", "svg", "tiff", "heic"]) {
            expect(getFileIcon(`photo.${ext}`)).toBe("🖼️");
        }
    });

    it("returns default icon for unknown extension", () => {
        expect(getFileIcon("archive.zip")).toBe("📎");
    });

    it("handles files with multiple dots", () => {
        expect(getFileIcon("my.report.final.pdf")).toBe("📄");
    });

    it("returns default for no extension", () => {
        expect(getFileIcon("README")).toBe("📎");
    });

    it("is case-insensitive", () => {
        expect(getFileIcon("REPORT.PDF")).toBe("📄");
        expect(getFileIcon("Data.XLSX")).toBe("📊");
    });
});

describe("formatFileSize", () => {
    it("returns dash for undefined", () => {
        expect(formatFileSize(undefined)).toBe("—");
    });

    it("returns '0 B' for 0 bytes", () => {
        expect(formatFileSize(0)).toBe("0 B");
    });

    it("formats bytes", () => {
        expect(formatFileSize(500)).toBe("500 B");
    });

    it("formats kilobytes", () => {
        expect(formatFileSize(1024)).toBe("1.0 KB");
        expect(formatFileSize(1536)).toBe("1.5 KB");
    });

    it("formats megabytes", () => {
        expect(formatFileSize(1048576)).toBe("1.0 MB");
        expect(formatFileSize(5242880)).toBe("5.0 MB");
    });

    it("formats gigabytes", () => {
        expect(formatFileSize(1073741824)).toBe("1.0 GB");
    });
});

describe("getFileExtension", () => {
    it("extracts extension", () => {
        expect(getFileExtension("doc.pdf")).toBe("pdf");
    });

    it("lowercases extension", () => {
        expect(getFileExtension("DOC.PDF")).toBe("pdf");
    });

    it("handles multiple dots", () => {
        expect(getFileExtension("my.file.txt")).toBe("txt");
    });

    it("returns empty for no extension", () => {
        expect(getFileExtension("README")).toBe("readme");
    });
});

describe("getFileContentUrl", () => {
    it("encodes the path", () => {
        expect(getFileContentUrl("my file.pdf")).toBe("/content/my%20file.pdf");
    });

    it("encodes special characters", () => {
        expect(getFileContentUrl("report (1).pdf")).toBe("/content/report%20(1).pdf");
    });

    it("appends folder as query param when provided", () => {
        expect(getFileContentUrl("report.pdf", "invoices")).toBe("/content/report.pdf?folder=invoices");
    });

    it("encodes folder name with spaces", () => {
        expect(getFileContentUrl("report.pdf", "my folder")).toBe("/content/report.pdf?folder=my%20folder");
    });
});
