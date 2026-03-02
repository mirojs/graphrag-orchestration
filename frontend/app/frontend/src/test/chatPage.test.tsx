import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { renderWithProviders } from "./testUtils";

// Mock authConfig
vi.mock("../authConfig", () => ({
    useLogin: true,
    getToken: vi.fn().mockResolvedValue("mock-token"),
    requireAccessControl: false,
    requireLogin: false,
}));

// Mock MSAL
vi.mock("@azure/msal-react", () => ({
    useMsal: () => ({ instance: { getActiveAccount: () => ({ username: "test" }) } }),
    MsalProvider: ({ children }: any) => children,
}));

// Mock loginContext
vi.mock("../loginContext", () => ({
    LoginContext: React.createContext({ loggedIn: true }),
}));

// Mock ndjson stream reader
vi.mock("ndjson-readablestream", () => ({
    default: vi.fn(),
}));

// Mock APIs
const mockChatApi = vi.fn();
const mockConfigApi = vi.fn().mockResolvedValue({
    showMultimodalOptions: false,
    showSemanticRankerOption: false,
    showQueryRewritingOption: false,
    showReasoningEffortOption: false,
    streamingEnabled: false,
    showVectorOption: false,
    showUserUpload: false,
    showLanguagePicker: false,
    showSpeechInput: false,
    showSpeechOutputBrowser: false,
    showSpeechOutputAzure: false,
    showChatHistoryBrowser: false,
    showChatHistoryCosmos: false,
    showAgenticRetrievalOption: false,
    ragSearchTextEmbeddings: true,
    ragSearchImageEmbeddings: false,
    ragSendTextSources: true,
    ragSendImageSources: false,
    webSourceEnabled: false,
    sharepointSourceEnabled: false,
    defaultReasoningEffort: "medium",
    defaultRetrievalReasoningEffort: "minimal",
});

vi.mock("../api", async () => {
    const actual = await vi.importActual("../api/models");
    return {
        ...actual,
        chatApi: (...args: any[]) => mockChatApi(...args),
        configApi: () => mockConfigApi(),
        getCitationFilePath: (name: string) => `/content/${name}`,
        RetrievalMode: { Hybrid: "hybrid", Vectors: "vectors", Text: "text" },
    };
});

// Mock HistoryProviders
vi.mock("../components/HistoryProviders", () => ({
    useHistoryManager: () => ({
        addItem: vi.fn(),
        getNextItems: vi.fn().mockResolvedValue([]),
        getItem: vi.fn(),
        deleteItem: vi.fn(),
        resetContinuationToken: vi.fn(),
    }),
    HistoryProviderOptions: { None: "none" },
}));

// Mock HistoryPanel
vi.mock("../components/HistoryPanel", () => ({
    HistoryPanel: () => null,
}));

// Mock SpeechOutputAzure/Browser
vi.mock("../components/Answer/SpeechOutputBrowser", () => ({
    SpeechOutputBrowser: () => null,
}));
vi.mock("../components/Answer/SpeechOutputAzure", () => ({
    SpeechOutputAzure: () => null,
}));

// Mock react-helmet-async
vi.mock("react-helmet-async", () => ({
    Helmet: ({ children }: any) => <>{children}</>,
}));

import { LoginContext } from "../loginContext";
const { default: Chat } = await import("../pages/chat/Chat");

function renderChat(loggedIn = true) {
    return renderWithProviders(
        <LoginContext.Provider value={{ loggedIn }}>
            <Chat />
        </LoginContext.Provider>
    );
}

describe("Chat page integration", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockConfigApi.mockResolvedValue({
            showMultimodalOptions: false,
            showSemanticRankerOption: false,
            showQueryRewritingOption: false,
            showReasoningEffortOption: false,
            streamingEnabled: false,
            showVectorOption: false,
            showUserUpload: false,
            showLanguagePicker: false,
            showSpeechInput: false,
            showSpeechOutputBrowser: false,
            showSpeechOutputAzure: false,
            showChatHistoryBrowser: false,
            showChatHistoryCosmos: false,
            showAgenticRetrievalOption: false,
            ragSearchTextEmbeddings: true,
            ragSearchImageEmbeddings: false,
            ragSendTextSources: true,
            ragSendImageSources: false,
            webSourceEnabled: false,
            sharepointSourceEnabled: false,
            defaultReasoningEffort: "medium",
            defaultRetrievalReasoningEffort: "minimal",
        });
    });

    it("renders sign-in prompt when not logged in", () => {
        renderChat(false);
        expect(screen.getByText("Sign in to start asking your documents")).toBeInTheDocument();
    });

    it("renders empty state with examples when logged in", async () => {
        renderChat(true);
        await waitFor(() => {
            expect(screen.getByRole("textbox")).toBeInTheDocument();
        });
    });

    it("renders settings button", async () => {
        renderChat(true);
        const settingsBtn = screen.getByRole("button", { name: /developer settings/i });
        expect(settingsBtn).toBeInTheDocument();
    });

    it("sends a question and shows the answer (non-streaming)", async () => {
        const responseData = {
            message: { content: "This is the answer", role: "assistant" },
            delta: { content: "", role: "assistant" },
            context: {
                data_points: { text: ["dp1"], images: [], citations: [] },
                followup_questions: null,
                thoughts: [{ title: "step1", description: "d" }],
            },
            session_state: null,
        };
        mockChatApi.mockResolvedValue({
            ok: true,
            status: 200,
            body: new ReadableStream(),
            json: () => Promise.resolve(responseData),
        });

        const user = userEvent.setup();
        renderChat(true);

        const textarea = screen.getByRole("textbox");
        await user.type(textarea, "What is this about?");
        await user.click(screen.getByRole("button", { name: "Submit question" }));

        await waitFor(
            () => {
                expect(screen.getByText("This is the answer")).toBeInTheDocument();
            },
            { timeout: 5000 }
        );
        expect(screen.getByText("What is this about?")).toBeInTheDocument();
    });

    it("shows error state on API failure", async () => {
        mockChatApi.mockRejectedValue(new Error("Server error"));

        const user = userEvent.setup();
        renderChat(true);

        const textarea = screen.getByRole("textbox");
        await user.type(textarea, "break it");
        await user.click(screen.getByRole("button", { name: "Submit question" }));

        await waitFor(() => {
            expect(screen.getByText("Retry")).toBeInTheDocument();
        });
    });

    it("clear chat resets the conversation", async () => {
        const responseData = {
            message: { content: "Answer text", role: "assistant" },
            delta: { content: "", role: "assistant" },
            context: {
                data_points: { text: [], images: [], citations: [] },
                followup_questions: null,
                thoughts: [],
            },
            session_state: null,
        };
        mockChatApi.mockResolvedValue({
            ok: true,
            status: 200,
            body: new ReadableStream(),
            json: () => Promise.resolve(responseData),
        });

        const user = userEvent.setup();
        renderChat(true);

        // Send a question
        await user.type(screen.getByRole("textbox"), "Hello");
        await user.click(screen.getByRole("button", { name: "Submit question" }));
        await waitFor(() => expect(screen.getByText("Answer text")).toBeInTheDocument());

        // Clear chat
        await user.click(screen.getByRole("button", { name: /clear chat/i }));

        // Answer should be gone, examples should return
        await waitFor(() => {
            expect(screen.queryByText("Answer text")).not.toBeInTheDocument();
        });
    });
});
