import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { AgentPlan } from "../components/AnalysisPanel/AgentPlan";
import { QueryPlanStep } from "../components/AnalysisPanel/agentPlanUtils";
import { renderWithProviders } from "./testUtils";

// Mock TokenUsageGraph (canvas-heavy)
vi.mock("../components/AnalysisPanel/TokenUsageGraph", () => ({
    TokenUsageGraph: ({ title }: { title: string }) => <div data-testid="token-graph">{title}</div>,
}));

// Mock syntax highlighter
vi.mock("react-syntax-highlighter", () => ({
    Light: Object.assign(
        ({ children }: { children: string }) => <pre data-testid="syntax">{children}</pre>,
        { registerLanguage: vi.fn() }
    ),
}));
vi.mock("react-syntax-highlighter/dist/esm/languages/hljs/json", () => ({ default: {} }));
vi.mock("react-syntax-highlighter/dist/esm/styles/hljs", () => ({ a11yLight: {} }));

function step(id: number, type: string, extra: Partial<QueryPlanStep> = {}): QueryPlanStep {
    return { id, type, ...extra } as QueryPlanStep;
}

describe("AgentPlan", () => {
    it("returns null for empty queryPlan", () => {
        const { container } = renderWithProviders(<AgentPlan queryPlan={[]} />);
        expect(container.textContent).toBe("");
    });

    it("renders single iteration header for single planning step", () => {
        const plan: QueryPlanStep[] = [
            step(1, "modelQueryPlanning"),
            step(2, "searchIndex", { search_index_arguments: { search: "test" }, knowledge_source_name: "docs" }),
            step(3, "modelAnswerSynthesis"),
        ];
        renderWithProviders(<AgentPlan queryPlan={plan} />);
        expect(screen.getByText("Execution steps")).toBeInTheDocument();
        expect(screen.queryByText(/Iteration/)).not.toBeInTheDocument();
    });

    it("renders multiple iteration headers for multiple planning steps", () => {
        const plan: QueryPlanStep[] = [
            step(1, "modelQueryPlanning"),
            step(2, "searchIndex", { search_index_arguments: { search: "q1" }, knowledge_source_name: "docs" }),
            step(3, "modelQueryPlanning"),
            step(4, "web", { web_arguments: { search: "q2" }, knowledge_source_name: "web" }),
        ];
        renderWithProviders(<AgentPlan queryPlan={plan} />);
        expect(screen.getByText("Iteration 1 Execution steps")).toBeInTheDocument();
        expect(screen.getByText("Iteration 2 Execution steps")).toBeInTheDocument();
    });

    it("shows step numbers", () => {
        const plan: QueryPlanStep[] = [
            step(1, "modelQueryPlanning"),
            step(2, "searchIndex", { search_index_arguments: { search: "find" }, knowledge_source_name: "idx" }),
        ];
        renderWithProviders(<AgentPlan queryPlan={plan} />);
        expect(screen.getByText("Step 1:")).toBeInTheDocument();
        expect(screen.getByText("Step 2:")).toBeInTheDocument();
    });

    it("shows search query in searchIndex detail", () => {
        const plan: QueryPlanStep[] = [
            step(1, "searchIndex", { search_index_arguments: { search: "my query" }, knowledge_source_name: "search index" }),
        ];
        renderWithProviders(<AgentPlan queryPlan={plan} />);
        expect(screen.getByText("my query")).toBeInTheDocument();
        expect(screen.getByText("search index")).toBeInTheDocument();
    });

    it("shows 'No results found' for search step without results", () => {
        const plan: QueryPlanStep[] = [
            step(1, "searchIndex", { search_index_arguments: { search: "q" }, knowledge_source_name: "idx" }),
        ];
        renderWithProviders(<AgentPlan queryPlan={plan} results={[]} />);
        expect(screen.getByText("No results found")).toBeInTheDocument();
    });

    it("renders document result links and calls onCitationClicked", () => {
        const onCitation = vi.fn();
        const plan: QueryPlanStep[] = [
            step(1, "searchIndex", { search_index_arguments: { search: "q" }, knowledge_source_name: "idx" }),
        ];
        const results = [
            { type: "searchIndex", activity: { query: "q" }, sourcepage: "report.pdf" },
        ];
        renderWithProviders(<AgentPlan queryPlan={plan} results={results} onCitationClicked={onCitation} />);
        const link = screen.getByText("report.pdf");
        fireEvent.click(link);
        expect(onCitation).toHaveBeenCalled();
    });

    it("calls onEffortExtracted with effort kind from agentic step", () => {
        const onEffort = vi.fn();
        const plan: QueryPlanStep[] = [
            step(1, "agenticReasoning", { retrieval_reasoning_effort: { kind: "high" } } as any),
        ];
        renderWithProviders(<AgentPlan queryPlan={plan} onEffortExtracted={onEffort} />);
        expect(onEffort).toHaveBeenCalledWith("high");
    });

    it("shows elapsed_ms in table", () => {
        const plan: QueryPlanStep[] = [
            step(1, "searchIndex", {
                search_index_arguments: { search: "q" },
                knowledge_source_name: "idx",
                elapsed_ms: 42,
            } as any),
        ];
        renderWithProviders(<AgentPlan queryPlan={plan} />);
        expect(screen.getByText("42")).toBeInTheDocument();
    });
});
