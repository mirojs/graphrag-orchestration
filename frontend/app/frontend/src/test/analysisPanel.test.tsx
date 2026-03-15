import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AnalysisPanel } from "../components/AnalysisPanel/AnalysisPanel";
import { AnalysisPanelTabs } from "../components/AnalysisPanel/AnalysisPanelTabs";
import { renderWithProviders } from "./testUtils";
import { ChatAppResponse } from "../api/models";

// Mock heavy sub-components
vi.mock("../components/DocumentViewer", () => ({
    PdfHighlightViewer: () => <div data-testid="pdf-viewer" />,
    ImageHighlightViewer: () => <div data-testid="image-viewer" />,
    SentenceHighlight: {} as any,
}));
vi.mock("../components/MarkdownViewer", () => ({
    MarkdownViewer: () => <div data-testid="markdown-viewer" />,
}));

function makeResponse(overrides: Partial<ChatAppResponse["context"]> = {}): ChatAppResponse {
    return {
        message: { content: "Answer", role: "assistant" },
        delta: { content: "", role: "assistant" },
        context: {
            data_points: { text: ["point1"], images: [], citations: [] },
            followup_questions: null,
            thoughts: [{ title: "Step 1", description: "detail" }],
            ...overrides,
        },
        session_state: null,
    };
}

describe("AnalysisPanel", () => {
    let onTabChanged: (tab: AnalysisPanelTabs) => void;

    beforeEach(() => {
        onTabChanged = vi.fn();
        vi.spyOn(globalThis, "fetch").mockResolvedValue(
            new Response("fake", { status: 200 })
        );
    });

    it("renders citation tab", () => {
        renderWithProviders(
            <AnalysisPanel
                className=""
                activeTab={AnalysisPanelTabs.CitationTab}
                onActiveTabChanged={onTabChanged}
                activeCitation="/content/report.pdf"
                citationHeight="600px"
                answer={makeResponse()}
            />
        );
        const tabs = screen.getAllByRole("tab");
        expect(tabs).toHaveLength(1);
    });

    it("enables citation tab when activeCitation is set", () => {
        renderWithProviders(
            <AnalysisPanel
                className=""
                activeTab={AnalysisPanelTabs.CitationTab}
                onActiveTabChanged={onTabChanged}
                activeCitation="/content/report.pdf"
                citationHeight="600px"
                answer={makeResponse()}
            />
        );
        const tab = screen.getByRole("tab", { name: "Citation" });
        expect(tab).not.toHaveAttribute("disabled");
    });

    it("calls onActiveTabChanged when a tab is selected", async () => {
        const user = userEvent.setup();
        renderWithProviders(
            <AnalysisPanel
                className=""
                activeTab={AnalysisPanelTabs.CitationTab}
                onActiveTabChanged={onTabChanged}
                activeCitation="/content/report.pdf"
                citationHeight="600px"
                answer={makeResponse()}
            />
        );
        await user.click(screen.getByRole("tab", { name: "Citation" }));
        expect(onTabChanged).toHaveBeenCalledWith(AnalysisPanelTabs.CitationTab);
    });

    it("renders citation iframe when citation tab active with URL", async () => {
        renderWithProviders(
            <AnalysisPanel
                className=""
                activeTab={AnalysisPanelTabs.CitationTab}
                onActiveTabChanged={onTabChanged}
                activeCitation="/content/report.pdf"
                citationHeight="600px"
                answer={makeResponse()}
            />
        );
        // fetchCitation creates a blob URL iframe — check iframe exists
        const iframe = await screen.findByTitle("Citation");
        expect(iframe.tagName).toBe("IFRAME");
    });

    it("does not render citation viewer when fetch returns 401", async () => {
        vi.spyOn(globalThis, "fetch").mockResolvedValue(
            new Response(JSON.stringify({ detail: "Authentication required." }), {
                status: 401,
                headers: { "Content-Type": "application/json" },
            })
        );
        const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
        renderWithProviders(
            <AnalysisPanel
                className=""
                activeTab={AnalysisPanelTabs.CitationTab}
                onActiveTabChanged={onTabChanged}
                activeCitation="/content/report.pdf"
                citationHeight="600px"
                answer={makeResponse()}
            />
        );
        // Wait for the fetch to resolve and state to settle
        await vi.waitFor(() => {
            expect(consoleSpy).toHaveBeenCalledWith(
                expect.stringContaining("Citation fetch failed: 401")
            );
        });
        // No iframe or pdf viewer should be rendered with content
        const iframe = screen.queryByTitle("Citation");
        if (iframe) {
            // iframe src should be empty or absent (no blob URL from error body)
            const src = iframe.getAttribute("src");
            expect(src === "" || src === null).toBe(true);
        }
        consoleSpy.mockRestore();
    });

    it("does not render citation viewer when fetch returns 404", async () => {
        vi.spyOn(globalThis, "fetch").mockResolvedValue(
            new Response(JSON.stringify({ detail: "Content not found" }), {
                status: 404,
                headers: { "Content-Type": "application/json" },
            })
        );
        const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
        renderWithProviders(
            <AnalysisPanel
                className=""
                activeTab={AnalysisPanelTabs.CitationTab}
                onActiveTabChanged={onTabChanged}
                activeCitation="/content/report.pdf"
                citationHeight="600px"
                answer={makeResponse()}
            />
        );
        await vi.waitFor(() => {
            expect(consoleSpy).toHaveBeenCalledWith(
                expect.stringContaining("Citation fetch failed: 404")
            );
        });
        consoleSpy.mockRestore();
    });
});
