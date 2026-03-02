import { describe, it, expect } from "vitest";
import { parseSupportingContentItem } from "../components/SupportingContent/SupportingContentParser";

describe("parseSupportingContentItem", () => {
    it("splits title and content on first colon-space", () => {
        const result = parseSupportingContentItem("report.pdf: This is the content");
        expect(result.title).toBe("report.pdf");
        expect(result.content).toBe("This is the content");
    });

    it("preserves colons in content after the first split", () => {
        const result = parseSupportingContentItem("doc.pdf: Key: Value: More");
        expect(result.title).toBe("doc.pdf");
        expect(result.content).toBe("Key: Value: More");
    });

    it("handles items with no colon (title only)", () => {
        const result = parseSupportingContentItem("just-a-title");
        expect(result.title).toBe("just-a-title");
        expect(result.content).toBe("");
    });

    it("sanitizes HTML in content (strips dangerous tags)", () => {
        const result = parseSupportingContentItem('doc.pdf: <script>alert("xss")</script>Safe text');
        expect(result.content).not.toContain("<script>");
        expect(result.content).toContain("Safe text");
    });

    it("preserves safe HTML in content", () => {
        const result = parseSupportingContentItem("doc.pdf: <b>bold</b> text");
        expect(result.content).toContain("<b>bold</b>");
    });
});
