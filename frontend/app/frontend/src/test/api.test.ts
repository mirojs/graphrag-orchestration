import { describe, it, expect } from "vitest";
import { getCitationFilePath } from "../api/api";

describe("getCitationFilePath", () => {
    it("returns content path for simple filename", () => {
        expect(getCitationFilePath("report.pdf")).toBe("/content/report.pdf");
    });

    it("strips parenthesized suffix", () => {
        expect(getCitationFilePath("report.pdf (page 3)")).toBe("/content/report.pdf");
    });

    it("strips all parenthesized content with greedy match", () => {
        // The regex removes from the first open-paren onward when followed by close-paren at end
        expect(getCitationFilePath("report (v2).pdf (section 1)")).toBe("/content/report");
    });

    it("handles citation with no parentheses", () => {
        expect(getCitationFilePath("my-file.docx")).toBe("/content/my-file.docx");
    });
});
