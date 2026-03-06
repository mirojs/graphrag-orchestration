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

    it("renders both tab roles", () => {
        renderWithProviders(
            <AnalysisPanel
                className=""
                activeTab={AnalysisPanelTabs.SupportingContentTab}
                onActiveTabChanged={onTabChanged}
                activeCitation={undefined}
                citationHeight="600px"
                answer={makeResponse()}
            />
        );
        const tabs = screen.getAllByRole("tab");
        expect(tabs).toHaveLength(2);
    });

    it("renders supporting content when tab is active", () => {
        renderWithProviders(
            <AnalysisPanel
                className=""
                activeTab={AnalysisPanelTabs.SupportingContentTab}
                onActiveTabChanged={onTabChanged}
                activeCitation={undefined}
                citationHeight="600px"
                answer={makeResponse()}
            />
        );
        // SupportingContent component renders data points
        expect(screen.getByText(/point1/)).toBeInTheDocument();
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
                activeTab={AnalysisPanelTabs.SupportingContentTab}
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
});
