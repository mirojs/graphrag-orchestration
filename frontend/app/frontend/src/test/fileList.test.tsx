import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { FileList } from "../components/FileManager/FileList";
import { renderWithProviders } from "./testUtils";

describe("FileList", () => {
    const files = ["report.pdf", "data.xlsx", "notes.md"];
    let onToggle: ReturnType<typeof vi.fn>;
    let onDelete: ReturnType<typeof vi.fn>;
    let onRename: ReturnType<typeof vi.fn>;

    function setup(overrides: Partial<Parameters<typeof FileList>[0]> = {}) {
        onToggle = vi.fn();
        onDelete = vi.fn();
        onRename = vi.fn();
        return renderWithProviders(
            <FileList
                files={files}
                selected={new Set<string>()}
                loading={false}
                onToggleSelect={onToggle}
                onDelete={onDelete}
                onRename={onRename}
                {...overrides}
            />
        );
    }

    it("renders loading state", () => {
        setup({ loading: true, files: [] });
        expect(screen.getByText("Loading files...")).toBeInTheDocument();
    });

    it("renders empty state when no files", () => {
        setup({ files: [] });
        expect(screen.getByText("No files yet")).toBeInTheDocument();
    });

    it("renders file names", () => {
        setup();
        expect(screen.getByText("report.pdf")).toBeInTheDocument();
        expect(screen.getByText("data.xlsx")).toBeInTheDocument();
        expect(screen.getByText("notes.md")).toBeInTheDocument();
    });

    it("renders file extensions as type", () => {
        setup();
        expect(screen.getByText("PDF")).toBeInTheDocument();
        expect(screen.getByText("XLSX")).toBeInTheDocument();
        expect(screen.getByText("MD")).toBeInTheDocument();
    });

    it("calls onToggleSelect when row is clicked", () => {
        setup();
        fireEvent.click(screen.getByText("report.pdf"));
        expect(onToggle).toHaveBeenCalledWith("report.pdf");
    });

    it("shows checked checkbox for selected files", () => {
        setup({ selected: new Set(["data.xlsx"]) });
        const checkboxes = screen.getAllByRole("checkbox");
        const dataCheckbox = checkboxes[1]; // second file
        expect(dataCheckbox).toBeChecked();
    });

    it("calls onRename when rename button is clicked", () => {
        setup();
        const renameButtons = screen.getAllByTitle("Rename");
        fireEvent.click(renameButtons[0]);
        expect(onRename).toHaveBeenCalledWith("report.pdf");
    });

    it("calls onDelete when delete button is clicked", () => {
        setup();
        const deleteButtons = screen.getAllByTitle("Delete");
        fireEvent.click(deleteButtons[1]);
        expect(onDelete).toHaveBeenCalledWith("data.xlsx");
    });

    it("does not call onToggleSelect when action buttons are clicked", () => {
        setup();
        const renameButtons = screen.getAllByTitle("Rename");
        fireEvent.click(renameButtons[0]);
        // onToggle should NOT be called because action div stops propagation
        expect(onToggle).not.toHaveBeenCalled();
    });
});
