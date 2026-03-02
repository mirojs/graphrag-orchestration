import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "./testUtils";
import { UserChatMessage } from "../components/UserChatMessage";

describe("UserChatMessage", () => {
    it("renders the message text", () => {
        renderWithProviders(<UserChatMessage message="Hello, how are you?" />);
        expect(screen.getByText("Hello, how are you?")).toBeInTheDocument();
    });

    it("renders long messages", () => {
        const longMessage = "A".repeat(500);
        renderWithProviders(<UserChatMessage message={longMessage} />);
        expect(screen.getByText(longMessage)).toBeInTheDocument();
    });
});
