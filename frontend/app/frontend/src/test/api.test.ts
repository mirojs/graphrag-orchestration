import { describe, it, expect } from "vitest";
import { getCitationFilePath } from "../api/api";

describe("getCitationFilePath", () => {
    it("returns content path for simple filename", () => {
        expect(getCitationFilePath("report.pdf")).toBe("/content/report.pdf");
    });

    it("strips last parenthesized suffix", () => {
        expect(getCitationFilePath("report.pdf (page 3)")).toBe("/content/report.pdf");
    });

    it("only strips the last parenthesized group, preserving parentheses in filename", () => {
        expect(getCitationFilePath("report (v2).pdf (section 1)")).toBe("/content/report%20(v2).pdf");
    });

    it("handles citation with no parentheses", () => {
        expect(getCitationFilePath("my-file.docx")).toBe("/content/my-file.docx");
    });

    it("encodes spaces and special characters", () => {
        expect(getCitationFilePath("my file.pdf")).toBe("/content/my%20file.pdf");
    });

    it("extracts filename from documentUrl when provided", () => {
        const docUrl = "https://storage.blob.core.windows.net/test-docs/PROPERTY%20MANAGEMENT%20AGREEMENT.pdf";
        expect(
            getCitationFilePath("PROPERTY MANAGEMENT AGREEMENT", docUrl)
        ).toBe(`/content/PROPERTY%20MANAGEMENT%20AGREEMENT.pdf?source=${encodeURIComponent(docUrl)}`);
    });

    it("uses citation as fallback when documentUrl is invalid", () => {
        expect(getCitationFilePath("report.pdf", "not-a-url")).toBe(`/content/report.pdf?source=${encodeURIComponent("not-a-url")}`);
    });

    it("uses citation as fallback when documentUrl has no path segments", () => {
        const docUrl = "https://example.com";
        expect(getCitationFilePath("report.pdf", docUrl)).toBe(`/content/report.pdf?source=${encodeURIComponent(docUrl)}`);
    });

    it("handles documentUrl with encoded special characters", () => {
        const docUrl = "https://storage.blob.core.windows.net/docs/My%20Report%20(v2).pdf";
        expect(
            getCitationFilePath("Agreement", docUrl)
        ).toBe(`/content/My%20Report%20(v2).pdf?source=${encodeURIComponent(docUrl)}`);
    });
});
