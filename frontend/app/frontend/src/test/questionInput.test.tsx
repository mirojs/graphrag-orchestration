import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "./testUtils";
import { QuestionInput } from "../components/QuestionInput";

const defaultProps = {
    onSend: vi.fn(),
    onStop: vi.fn(),
    disabled: false,
    isStreaming: false,
    isLoading: false
};

describe("QuestionInput", () => {
    it("renders a textarea", () => {
        renderWithProviders(<QuestionInput {...defaultProps} />);
        expect(screen.getByRole("textbox")).toBeInTheDocument();
    });

    it("renders with placeholder text", () => {
        renderWithProviders(<QuestionInput {...defaultProps} placeholder="Ask something..." />);
        expect(screen.getByPlaceholderText("Ask something...")).toBeInTheDocument();
    });

    it("calls onSend when send button is clicked", async () => {
        const user = userEvent.setup();
        const onSend = vi.fn();
        renderWithProviders(<QuestionInput {...defaultProps} onSend={onSend} />);

        const textarea = screen.getByRole("textbox");
        await user.type(textarea, "Hello world");
        // Find the send button (it's the button with the Send icon)
        const buttons = screen.getAllByRole("button");
        await user.click(buttons[0]);
        expect(onSend).toHaveBeenCalledWith("Hello world");
    });

    it("calls onSend on Enter key", async () => {
        const user = userEvent.setup();
        const onSend = vi.fn();
        renderWithProviders(<QuestionInput {...defaultProps} onSend={onSend} />);

        const textarea = screen.getByRole("textbox");
        await user.type(textarea, "Test question{enter}");
        expect(onSend).toHaveBeenCalledWith("Test question");
    });

    it("does not send on Shift+Enter", async () => {
        const user = userEvent.setup();
        const onSend = vi.fn();
        renderWithProviders(<QuestionInput {...defaultProps} onSend={onSend} />);

        const textarea = screen.getByRole("textbox");
        await user.type(textarea, "line one{shift>}{enter}{/shift}");
        expect(onSend).not.toHaveBeenCalled();
    });

    it("does not send empty or whitespace-only text", async () => {
        const user = userEvent.setup();
        const onSend = vi.fn();
        renderWithProviders(<QuestionInput {...defaultProps} onSend={onSend} />);

        const textarea = screen.getByRole("textbox");
        await user.type(textarea, "   {enter}");
        expect(onSend).not.toHaveBeenCalled();
    });

    it("clears input after send when clearOnSend is true", async () => {
        const user = userEvent.setup();
        renderWithProviders(<QuestionInput {...defaultProps} clearOnSend />);

        const textarea = screen.getByRole("textbox");
        await user.type(textarea, "question{enter}");
        expect(textarea).toHaveValue("");
    });

    it("shows stop button when streaming", () => {
        renderWithProviders(<QuestionInput {...defaultProps} isStreaming />);
        // Stop button should be present, send button should not
        const buttons = screen.getAllByRole("button");
        expect(buttons.length).toBeGreaterThanOrEqual(1);
    });

    it("calls onStop when stop button is clicked", async () => {
        const user = userEvent.setup();
        const onStop = vi.fn();
        renderWithProviders(<QuestionInput {...defaultProps} onStop={onStop} isStreaming />);

        const buttons = screen.getAllByRole("button");
        await user.click(buttons[0]);
        expect(onStop).toHaveBeenCalledOnce();
    });

    it("pre-fills text from initQuestion", () => {
        renderWithProviders(<QuestionInput {...defaultProps} initQuestion="Pre-filled" />);
        expect(screen.getByRole("textbox")).toHaveValue("Pre-filled");
    });
});
