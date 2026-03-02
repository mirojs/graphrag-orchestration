import { describe, it, expect, vi } from "vitest";
import { parseAnswerToHtml, extractCitationDetails } from "../components/Answer/AnswerParser";
import { ChatAppResponse } from "../api/models";

// Helper to build a minimal ChatAppResponse
function makeResponse(content: string, citations: string[] = [], overrides?: Partial<ChatAppResponse["context"]>): ChatAppResponse {
    return {
        message: { content, role: "assistant" },
        delta: { content: "", role: "assistant" },
        context: {
            data_points: {
                text: [],
                images: [],
                citations,
                citation_activity_details: overrides?.data_points?.citation_activity_details ?? {},
                external_results_metadata: overrides?.data_points?.external_results_metadata ?? []
            },
            followup_questions: null,
            thoughts: overrides?.thoughts ?? [],
            ...(overrides ?? {})
        },
        session_state: null
    };
}

describe("parseAnswerToHtml", () => {
    const noopClick = vi.fn();

    it("returns plain text when no citations", () => {
        const response = makeResponse("Hello world");
        const result = parseAnswerToHtml(response, false, noopClick);
        expect(result.answerHtml).toBe("Hello world");
        expect(result.citations).toHaveLength(0);
    });

    it("parses a single document citation", () => {
        const response = makeResponse("See [report.pdf] for details.", ["report.pdf"]);
        const result = parseAnswerToHtml(response, false, noopClick);
        expect(result.citations).toHaveLength(1);
        expect(result.citations[0].reference).toBe("report.pdf");
        expect(result.citations[0].index).toBe(1);
        expect(result.citations[0].isWeb).toBe(false);
        expect(result.answerHtml).toContain("supContainer");
    });

    it("parses multiple distinct citations", () => {
        const response = makeResponse("See [a.pdf] and [b.pdf].", ["a.pdf", "b.pdf"]);
        const result = parseAnswerToHtml(response, false, noopClick);
        expect(result.citations).toHaveLength(2);
        expect(result.citations[0].index).toBe(1);
        expect(result.citations[1].index).toBe(2);
    });

    it("deduplicates repeated citations", () => {
        const response = makeResponse("[a.pdf] then [a.pdf].", ["a.pdf"]);
        const result = parseAnswerToHtml(response, false, noopClick);
        expect(result.citations).toHaveLength(1);
    });

    it("ignores invalid citations not in possibleCitations", () => {
        const response = makeResponse("See [unknown.pdf].", ["real.pdf"]);
        const result = parseAnswerToHtml(response, false, noopClick);
        expect(result.citations).toHaveLength(0);
        expect(result.answerHtml).toContain("[unknown.pdf]");
    });

    it("identifies web citations", () => {
        const url = "https://example.com/article";
        const response = makeResponse(`See [${url}].`, [url]);
        const result = parseAnswerToHtml(response, false, noopClick);
        expect(result.citations).toHaveLength(1);
        expect(result.citations[0].isWeb).toBe(true);
        expect(result.answerHtml).toContain('href="https://example.com/article"');
        expect(result.answerHtml).toContain('target="_blank"');
    });

    it("strips incomplete citation brackets when streaming", () => {
        const response = makeResponse("Answer text [incompl", ["incomplete.pdf"]);
        const result = parseAnswerToHtml(response, true, noopClick);
        expect(result.answerHtml).toBe("Answer text ");
    });

    it("keeps complete citations when streaming", () => {
        const response = makeResponse("Answer [doc.pdf] more text", ["doc.pdf"]);
        const result = parseAnswerToHtml(response, true, noopClick);
        expect(result.citations).toHaveLength(1);
    });

    it("resolves SharePoint filename to URL from external_results_metadata", () => {
        const response = makeResponse("See [report.pdf].", ["report.pdf"], {
            data_points: {
                text: [],
                images: [],
                citations: ["report.pdf"],
                external_results_metadata: [
                    { url: "https://sharepoint.com/sites/docs/report.pdf", title: "Report" }
                ]
            },
            followup_questions: null,
            thoughts: []
        });
        const result = parseAnswerToHtml(response, false, noopClick);
        expect(result.citations[0].reference).toBe("https://sharepoint.com/sites/docs/report.pdf");
        expect(result.citations[0].isWeb).toBe(true);
    });

    it("attaches step metadata from citation_activity_details", () => {
        const response = makeResponse("See [doc.pdf].", ["doc.pdf"], {
            data_points: {
                text: [],
                images: [],
                citations: ["doc.pdf"],
                citation_activity_details: {
                    "doc.pdf": { id: "1", number: 2, type: "searchIndex", source: "Knowledge Base" }
                }
            },
            followup_questions: null,
            thoughts: []
        });
        const result = parseAnswerToHtml(response, false, noopClick);
        expect(result.citations[0].stepNumber).toBe(2);
        expect(result.citations[0].stepLabel).toBe("Index search");
        expect(result.citations[0].stepSource).toBe("Knowledge Base");
    });
});

describe("extractCitationDetails", () => {
    it("returns citation list without HTML", () => {
        const response = makeResponse("See [a.pdf] and [b.pdf].", ["a.pdf", "b.pdf"]);
        const details = extractCitationDetails(response);
        expect(details).toHaveLength(2);
        expect(details[0].reference).toBe("a.pdf");
        expect(details[1].reference).toBe("b.pdf");
    });

    it("returns empty array when no citations", () => {
        const response = makeResponse("No citations here.");
        expect(extractCitationDetails(response)).toHaveLength(0);
    });
});
