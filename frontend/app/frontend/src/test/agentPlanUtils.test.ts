import { describe, it, expect } from "vitest";
import { getStepLabel, activityTypeLabels } from "../components/AnalysisPanel/agentPlanUtils";
import type { QueryPlanStep } from "../components/AnalysisPanel/agentPlanUtils";

describe("activityTypeLabels", () => {
    it("maps all expected activity types", () => {
        expect(activityTypeLabels["searchIndex"]).toBe("Index search");
        expect(activityTypeLabels["web"]).toBe("Web search");
        expect(activityTypeLabels["remoteSharePoint"]).toBe("SharePoint search");
        expect(activityTypeLabels["modelQueryPlanning"]).toBe("Query planning");
        expect(activityTypeLabels["agenticReasoning"]).toBe("Agentic reasoning");
        expect(activityTypeLabels["modelAnswerSynthesis"]).toBe("Answer synthesis");
    });
});

describe("getStepLabel", () => {
    it("prefers step.label when present", () => {
        const step: QueryPlanStep = { id: 1, type: "searchIndex", label: "Custom Label" };
        expect(getStepLabel(step)).toBe("Custom Label");
    });

    it("falls back to activityTypeLabels when no label", () => {
        const step: QueryPlanStep = { id: 2, type: "web" };
        expect(getStepLabel(step)).toBe("Web search");
    });

    it("falls back to raw type when no label and no mapping", () => {
        const step: QueryPlanStep = { id: 3, type: "unknownType" };
        expect(getStepLabel(step)).toBe("unknownType");
    });
});
