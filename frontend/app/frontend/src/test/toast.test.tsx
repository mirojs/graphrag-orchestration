import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "./testUtils";
import { Toast } from "../components/FileManager/Toast";

describe("Toast", () => {
    it("renders success toast with text", () => {
        renderWithProviders(<Toast type="success" text="File uploaded" onDismiss={vi.fn()} />);
        expect(screen.getByText("File uploaded")).toBeInTheDocument();
        expect(screen.getByText("✅")).toBeInTheDocument();
    });

    it("renders error toast with icon", () => {
        renderWithProviders(<Toast type="error" text="Upload failed" onDismiss={vi.fn()} />);
        expect(screen.getByText("Upload failed")).toBeInTheDocument();
        expect(screen.getByText("❌")).toBeInTheDocument();
    });

    it("renders info toast with icon", () => {
        renderWithProviders(<Toast type="info" text="Processing..." onDismiss={vi.fn()} />);
        expect(screen.getByText("Processing...")).toBeInTheDocument();
        expect(screen.getByText("ℹ️")).toBeInTheDocument();
    });

    it("calls onDismiss when dismiss button is clicked", async () => {
        const user = userEvent.setup();
        const onDismiss = vi.fn();
        renderWithProviders(<Toast type="success" text="Done" onDismiss={onDismiss} />);

        await user.click(screen.getByText("✕"));
        expect(onDismiss).toHaveBeenCalledOnce();
    });
});
