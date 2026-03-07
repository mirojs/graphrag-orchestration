import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "./testUtils";

// Mock authConfig before importing Files
vi.mock("../authConfig", () => ({
    useLogin: true,
    requireLogin: true,
    getToken: vi.fn().mockResolvedValue("mock-token"),
}));

// Mock MSAL
vi.mock("@azure/msal-react", () => ({
    useMsal: () => ({ instance: { getActiveAccount: () => ({ username: "test" }) } }),
    MsalProvider: ({ children }: any) => children,
}));

// Mock loginContext
vi.mock("../loginContext", () => ({
    LoginContext: {
        _currentValue: { loggedIn: true },
        Provider: ({ children }: any) => children,
        Consumer: ({ children }: any) => children({ loggedIn: true }),
    },
}));

// Mock file APIs
const mockListFiles = vi.fn().mockResolvedValue(["report.pdf", "data.xlsx", "notes.md"]);
const mockUploadFiles = vi.fn().mockResolvedValue({ message: "Uploaded" });
const mockDeleteFile = vi.fn().mockResolvedValue({});
const mockBulkDelete = vi.fn().mockResolvedValue({});
const mockRenameFile = vi.fn().mockResolvedValue({});

vi.mock("../api/files", () => ({
    listFilesApi: (...args: any[]) => mockListFiles(...args),
    uploadFilesApi: (...args: any[]) => mockUploadFiles(...args),
    deleteFileApi: (...args: any[]) => mockDeleteFile(...args),
    bulkDeleteFilesApi: (...args: any[]) => mockBulkDelete(...args),
    renameFileApi: (...args: any[]) => mockRenameFile(...args),
    getFileIcon: (name: string) => "📄",
    ACCEPTED_FILE_TYPES: ".pdf,.docx,.xlsx",
}));

// Need React context for LoginContext
import React from "react";
import { LoginContext } from "../loginContext";

// Import after mocks
const { default: Files } = await import("../pages/files/Files");

function renderFiles() {
    return renderWithProviders(
        <LoginContext.Provider value={{ loggedIn: true, setLoggedIn: () => {} }}>
            <Files />
        </LoginContext.Provider>
    );
}

describe("Files page integration", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockListFiles.mockResolvedValue(["report.pdf", "data.xlsx", "notes.md"]);
        window.confirm = vi.fn().mockReturnValue(true);
    });

    it("loads and displays files on mount", async () => {
        renderFiles();
        await waitFor(() => {
            expect(screen.getByText("report.pdf")).toBeInTheDocument();
        });
        expect(screen.getByText("data.xlsx")).toBeInTheDocument();
        expect(screen.getByText("notes.md")).toBeInTheDocument();
    });

    it("shows loading state while files load", () => {
        mockListFiles.mockReturnValue(new Promise(() => {})); // never resolves
        renderFiles();
        expect(screen.getByText("Loading files...")).toBeInTheDocument();
    });

    it("shows empty state when no files", async () => {
        mockListFiles.mockResolvedValue([]);
        renderFiles();
        await waitFor(() => {
            expect(screen.getByText("No files yet")).toBeInTheDocument();
        });
    });

    it("filters files by search query", async () => {
        const user = userEvent.setup();
        renderFiles();
        await waitFor(() => expect(screen.getByText("report.pdf")).toBeInTheDocument());

        const searchInput = screen.getByPlaceholderText(/search/i);
        await user.type(searchInput, "report");

        expect(screen.getByText("report.pdf")).toBeInTheDocument();
        expect(screen.queryByText("data.xlsx")).not.toBeInTheDocument();
    });

    it("opens rename dialog when rename is clicked", async () => {
        renderFiles();
        await waitFor(() => expect(screen.getByText("report.pdf")).toBeInTheDocument());

        const renameButtons = screen.getAllByTitle("Rename");
        await userEvent.click(renameButtons[0]);

        expect(screen.getByText("Rename File")).toBeInTheDocument();
    });

    it("calls delete API and refreshes file list", async () => {
        renderFiles();
        await waitFor(() => expect(screen.getByText("report.pdf")).toBeInTheDocument());

        const deleteButtons = screen.getAllByTitle("Delete");
        await userEvent.click(deleteButtons[0]);

        expect(window.confirm).toHaveBeenCalled();
        await waitFor(() => expect(mockDeleteFile).toHaveBeenCalled());
    });
});
