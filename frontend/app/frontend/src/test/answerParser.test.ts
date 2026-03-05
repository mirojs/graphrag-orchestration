import { describe, it, expect, vi } from "vitest";
import { parseAnswerToHtml, extractCitationDetails } from "../components/Answer/AnswerParser";
import { ChatAppResponse, StructuredCitation } from "../api/models";

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
                external_results_metadata: overrides?.data_points?.external_results_metadata ?? [],
                structured_citations: overrides?.data_points?.structured_citations ?? []
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

    // --- Structured citation [N] marker tests ---

    it("matches [N] markers against structured_citations", () => {
        const sc: StructuredCitation[] = [
            { citation: "[1]", document_title: "Contract.pdf", page_number: 3, sentence_text: "Delivery in 30 days" },
            { citation: "[2]", document_title: "Invoice.pdf", page_number: 1, sentence_text: "Total: $5000" }
        ];
        const response = makeResponse("Delivery is 30 days [1]. Total is $5000 [2].", [], {
            data_points: { text: [], images: [], citations: [], structured_citations: sc }
        });
        const result = parseAnswerToHtml(response, false, noopClick);
        expect(result.citations).toHaveLength(2);
        expect(result.citations[0].reference).toBe("Contract.pdf");
        expect(result.citations[0].citationKey).toBe("[1]");
        expect(result.citations[1].reference).toBe("Invoice.pdf");
        expect(result.citations[1].citationKey).toBe("[2]");
        expect(result.answerHtml).toContain("supContainer");
    });

    it("extracts filename from document_url to preserve extension", () => {
        const sc: StructuredCitation[] = [
            { citation: "[1]", document_title: "Contract", document_url: "https://blob.example.com/docs/Contract.pdf" }
        ];
        const response = makeResponse("See [1].", [], {
            data_points: { text: [], images: [], citations: [], structured_citations: sc }
        });
        const result = parseAnswerToHtml(response, false, noopClick);
        expect(result.citations[0].reference).toBe("Contract.pdf");
        expect(result.citations[0].isWeb).toBe(false);
    });

    it("deduplicates repeated [N] markers", () => {
        const sc: StructuredCitation[] = [
            { citation: "[1]", document_title: "Contract.pdf" }
        ];
        const response = makeResponse("Fact [1]. Another fact [1].", [], {
            data_points: { text: [], images: [], citations: [], structured_citations: sc }
        });
        const result = parseAnswerToHtml(response, false, noopClick);
        expect(result.citations).toHaveLength(1);
    });

    it("handles [Na] sentence-level markers", () => {
        const sc: StructuredCitation[] = [
            { citation: "[1a]", citation_type: "sentence", document_title: "Contract.pdf", sentence_text: "First sentence" },
            { citation: "[1b]", citation_type: "sentence", document_title: "Contract.pdf", sentence_text: "Second sentence" }
        ];
        const response = makeResponse("Fact one [1a]. Fact two [1b].", [], {
            data_points: { text: [], images: [], citations: [], structured_citations: sc }
        });
        const result = parseAnswerToHtml(response, false, noopClick);
        expect(result.citations).toHaveLength(2);
        expect(result.citations[0].citationKey).toBe("[1a]");
        expect(result.citations[1].citationKey).toBe("[1b]");
    });

    it("ignores [N] markers not in structured_citations", () => {
        const sc: StructuredCitation[] = [
            { citation: "[1]", document_title: "Contract.pdf" }
        ];
        const response = makeResponse("Valid [1]. Invalid [99].", [], {
            data_points: { text: [], images: [], citations: [], structured_citations: sc }
        });
        const result = parseAnswerToHtml(response, false, noopClick);
        expect(result.citations).toHaveLength(1);
        expect(result.answerHtml).toContain("[99]");
    });

    it("mixes structured [N] and legacy filename citations", () => {
        const sc: StructuredCitation[] = [
            { citation: "[1]", document_title: "Contract.pdf" }
        ];
        const response = makeResponse("Graph [1]. Also see [other.pdf].", ["other.pdf"], {
            data_points: { text: [], images: [], citations: ["other.pdf"], structured_citations: sc }
        });
        const result = parseAnswerToHtml(response, false, noopClick);
        expect(result.citations).toHaveLength(2);
        expect(result.citations[0].citationKey).toBe("[1]");
        expect(result.citations[1].reference).toBe("other.pdf");
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

    it("extracts structured citation details", () => {
        const sc: StructuredCitation[] = [
            { citation: "[1]", document_title: "Report.pdf", sentence_text: "Key finding" }
        ];
        const response = makeResponse("Finding [1].", [], {
            data_points: { text: [], images: [], citations: [], structured_citations: sc }
        });
        const details = extractCitationDetails(response);
        expect(details).toHaveLength(1);
        expect(details[0].citationKey).toBe("[1]");
    });

    it("passes documentUrl through CitationDetail for structured citations", () => {
        const sc: StructuredCitation[] = [
            {
                citation: "[1]",
                document_title: "purchase contract",
                document_url: "https://storage.blob.core.windows.net/docs/PURCHASE%20CONTRACT.pdf",
                sentence_text: "The tenant shall pay rent"
            }
        ];
        const response = makeResponse("See [1].", [], {
            data_points: { text: [], images: [], citations: [], structured_citations: sc }
        });
        const details = extractCitationDetails(response);
        expect(details).toHaveLength(1);
        expect(details[0].documentUrl).toBe("https://storage.blob.core.windows.net/docs/PURCHASE%20CONTRACT.pdf");
        // reference should be extracted from document_url, not document_title
        expect(details[0].reference).toBe("PURCHASE CONTRACT.pdf");
    });

    it("emits data-citation-key attribute in rendered HTML", () => {
        const sc: StructuredCitation[] = [
            { citation: "[1]", document_title: "report.pdf", sentence_text: "Finding A" }
        ];
        const response = makeResponse("See [1].", [], {
            data_points: { text: [], images: [], citations: [], structured_citations: sc }
        });
        const result = parseAnswerToHtml(response, false, vi.fn());
        expect(result.answerHtml).toContain('data-citation-key="[1]"');
        expect(result.answerHtml).toContain('data-citation-path=');
    });

    it("uses document_url in getCitationFilePath for inline badges", () => {
        const sc: StructuredCitation[] = [
            {
                citation: "[1]",
                document_title: "purchase contract",
                document_url: "https://storage.blob.core.windows.net/docs/PURCHASE%20CONTRACT.pdf"
            }
        ];
        const response = makeResponse("See [1].", [], {
            data_points: { text: [], images: [], citations: [], structured_citations: sc }
        });
        const result = parseAnswerToHtml(response, false, vi.fn());
        // The path should use the filename from document_url, not the document_title
        expect(result.answerHtml).toContain("PURCHASE%20CONTRACT.pdf");
        expect(result.answerHtml).not.toContain("/content/purchase%20contract\"");
    });
});
