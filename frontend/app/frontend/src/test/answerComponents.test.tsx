import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "./testUtils";

import { AnswerIcon } from "../components/Answer/AnswerIcon";
import { AnswerLoading } from "../components/Answer/AnswerLoading";
import { AnswerError } from "../components/Answer/AnswerError";

describe("AnswerIcon", () => {
    it("renders sparkle icon", () => {
        const { container } = renderWithProviders(<AnswerIcon />);
        expect(container.querySelector("svg")).toBeTruthy();
    });
});

describe("AnswerLoading", () => {
    it("renders loading text", () => {
        renderWithProviders(<AnswerLoading />);
        expect(screen.getByText(/Generating answer/i)).toBeInTheDocument();
    });
});

describe("AnswerError", () => {
    it("renders error message and retry button", () => {
        const onRetry = vi.fn();
        renderWithProviders(<AnswerError error="Something went wrong" onRetry={onRetry} />);
        expect(screen.getByText("Something went wrong")).toBeInTheDocument();
        expect(screen.getByRole("button")).toBeInTheDocument();
    });

    it("calls onRetry when button clicked", async () => {
        const user = userEvent.setup();
        const onRetry = vi.fn();
        renderWithProviders(<AnswerError error="fail" onRetry={onRetry} />);
        await user.click(screen.getByRole("button"));
        expect(onRetry).toHaveBeenCalledOnce();
    });
});
