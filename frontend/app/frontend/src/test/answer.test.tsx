import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { Answer } from "../components/Answer/Answer";
import { renderWithProviders } from "./testUtils";
import { ChatAppResponse, SpeechConfig } from "../api/models";

// Mock sub-components that have heavy deps
vi.mock("../components/Answer/SpeechOutputBrowser", () => ({
    SpeechOutputBrowser: () => <div data-testid="speech-browser" />,
}));
vi.mock("../components/Answer/SpeechOutputAzure", () => ({
    SpeechOutputAzure: () => <div data-testid="speech-azure" />,
}));

function makeSpeechConfig(): SpeechConfig {
    return {
        speechUrls: [],
        setSpeechUrls: vi.fn(),
        audio: new Audio(),
        isPlaying: false,
        setIsPlaying: vi.fn(),
    };
}

function makeResponse(overrides: Partial<ChatAppResponse> = {}): ChatAppResponse {
    return {
        message: { content: "Test answer", role: "assistant" },
        delta: { content: "", role: "assistant" },
        context: {
            data_points: { text: ["dp1"], images: [], citations: [] },
            followup_questions: null,
            thoughts: [{ title: "step1", description: "thought detail" }],
        },
        session_state: null,
        ...overrides,
    };
}

describe("Answer component", () => {
    let onCitation: ReturnType<typeof vi.fn>;
    let onThought: ReturnType<typeof vi.fn>;
    let onSupporting: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        onCitation = vi.fn();
        onThought = vi.fn();
        onSupporting = vi.fn();
    });

    it("renders answer text via markdown", () => {
        renderWithProviders(
            <Answer
                answer={makeResponse()}
                index={0}
                speechConfig={makeSpeechConfig()}
                isStreaming={false}
                onCitationClicked={onCitation}
                onThoughtProcessClicked={onThought}
                onSupportingContentClicked={onSupporting}
            />
        );
        expect(screen.getByText("Test answer")).toBeInTheDocument();
    });

    it("disables thought process button when streaming", () => {
        renderWithProviders(
            <Answer
                answer={makeResponse()}
                index={0}
                speechConfig={makeSpeechConfig()}
                isStreaming={true}
                onCitationClicked={onCitation}
                onThoughtProcessClicked={onThought}
                onSupportingContentClicked={onSupporting}
            />
        );
        const thoughtBtn = screen.getByTitle("Show thought process");
        expect(thoughtBtn).toBeDisabled();
    });

    it("disables thought process button when no thoughts", () => {
        const resp = makeResponse({
            context: { data_points: { text: [], images: [], citations: [] }, followup_questions: null, thoughts: [] },
        });
        renderWithProviders(
            <Answer
                answer={resp}
                index={0}
                speechConfig={makeSpeechConfig()}
                isStreaming={false}
                onCitationClicked={onCitation}
                onThoughtProcessClicked={onThought}
                onSupportingContentClicked={onSupporting}
            />
        );
        const thoughtBtn = screen.getByTitle("Show thought process");
        expect(thoughtBtn).toBeDisabled();
    });

    it("calls onThoughtProcessClicked when thought button is clicked", () => {
        renderWithProviders(
            <Answer
                answer={makeResponse()}
                index={0}
                speechConfig={makeSpeechConfig()}
                isStreaming={false}
                onCitationClicked={onCitation}
                onThoughtProcessClicked={onThought}
                onSupportingContentClicked={onSupporting}
            />
        );
        fireEvent.click(screen.getByTitle("Show thought process"));
        expect(onThought).toHaveBeenCalledOnce();
    });

    it("calls onSupportingContentClicked when supporting button is clicked", () => {
        renderWithProviders(
            <Answer
                answer={makeResponse()}
                index={0}
                speechConfig={makeSpeechConfig()}
                isStreaming={false}
                onCitationClicked={onCitation}
                onThoughtProcessClicked={onThought}
                onSupportingContentClicked={onSupporting}
            />
        );
        fireEvent.click(screen.getByTitle("Show supporting content"));
        expect(onSupporting).toHaveBeenCalledOnce();
    });

    it("copies answer text to clipboard on copy button click", async () => {
        const mockWrite = vi.fn().mockResolvedValue(undefined);
        Object.assign(navigator, { clipboard: { writeText: mockWrite } });

        renderWithProviders(
            <Answer
                answer={makeResponse()}
                index={0}
                speechConfig={makeSpeechConfig()}
                isStreaming={false}
                onCitationClicked={onCitation}
                onThoughtProcessClicked={onThought}
                onSupportingContentClicked={onSupporting}
            />
        );
        fireEvent.click(screen.getByTitle("Copy"));
        await waitFor(() => expect(mockWrite).toHaveBeenCalledWith("Test answer"));
    });

    it("renders follow-up questions when provided", () => {
        const onFollowup = vi.fn();
        const resp = makeResponse({
            context: {
                data_points: { text: [], images: [], citations: [] },
                followup_questions: ["What else?", "Tell me more"],
                thoughts: [],
            },
        });
        renderWithProviders(
            <Answer
                answer={resp}
                index={0}
                speechConfig={makeSpeechConfig()}
                isStreaming={false}
                onCitationClicked={onCitation}
                onThoughtProcessClicked={onThought}
                onSupportingContentClicked={onSupporting}
                onFollowupQuestionClicked={onFollowup}
                showFollowupQuestions={true}
            />
        );
        expect(screen.getByText("What else?")).toBeInTheDocument();
        expect(screen.getByText("Tell me more")).toBeInTheDocument();
    });

    it("calls onFollowupQuestionClicked when a follow-up is clicked", () => {
        const onFollowup = vi.fn();
        const resp = makeResponse({
            context: {
                data_points: { text: [], images: [], citations: [] },
                followup_questions: ["What else?"],
                thoughts: [],
            },
        });
        renderWithProviders(
            <Answer
                answer={resp}
                index={0}
                speechConfig={makeSpeechConfig()}
                isStreaming={false}
                onCitationClicked={onCitation}
                onThoughtProcessClicked={onThought}
                onSupportingContentClicked={onSupporting}
                onFollowupQuestionClicked={onFollowup}
                showFollowupQuestions={true}
            />
        );
        fireEvent.click(screen.getByText("What else?"));
        expect(onFollowup).toHaveBeenCalledWith("What else?");
    });

    it("shows SpeechOutputAzure when showSpeechOutputAzure is true", () => {
        renderWithProviders(
            <Answer
                answer={makeResponse()}
                index={0}
                speechConfig={makeSpeechConfig()}
                isStreaming={false}
                onCitationClicked={onCitation}
                onThoughtProcessClicked={onThought}
                onSupportingContentClicked={onSupporting}
                showSpeechOutputAzure={true}
            />
        );
        expect(screen.getByTestId("speech-azure")).toBeInTheDocument();
    });

    it("shows SpeechOutputBrowser when showSpeechOutputBrowser is true", () => {
        renderWithProviders(
            <Answer
                answer={makeResponse()}
                index={0}
                speechConfig={makeSpeechConfig()}
                isStreaming={false}
                onCitationClicked={onCitation}
                onThoughtProcessClicked={onThought}
                onSupportingContentClicked={onSupporting}
                showSpeechOutputBrowser={true}
            />
        );
        expect(screen.getByTestId("speech-browser")).toBeInTheDocument();
    });
});
