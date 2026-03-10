/**
 * Test utilities: render wrapper with FluentUI + i18n + Router providers.
 */
import React from "react";
import { render, RenderOptions } from "@testing-library/react";
import { FluentProvider, webLightTheme } from "@fluentui/react-components";
import { MemoryRouter } from "react-router-dom";
import i18next from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";

// Minimal i18n instance for tests — returns keys as-is
const i18nInstance = i18next.createInstance();
i18nInstance.use(initReactI18next).init({
    lng: "en",
    fallbackLng: "en",
    resources: {
        en: {
            translation: {
                clearChat: "Clear chat",
                developerSettings: "Developer settings",
                generatingAnswer: "Generating answer",
                chat: "Chat",
                login: "Login",
                logout: "Logout",
                citationWithColon: "Citation:",
                followupQuestions: "Follow-up questions:",
                retry: "Retry",
                "errors.retry": "Retry",
                "history.openChatHistory": "Open chat history",
                "history.chatHistory": "Chat history",
                "history.noHistory": "No history",
                "labels.closeButton": "Close",
                "tooltips.submitQuestion": "Submit question",
                "tooltips.copy": "Copy",
                "tooltips.copied": "Copied!",
                "headerTexts.citation": "Citation",
                "errors.networkError": "Unable to reach the server. Please check your internet connection and try again.",
                "errors.timeoutError": "The request took too long. Please try again.",
                "errors.serverError": "Something went wrong on our end. Please try again in a moment.",
                "errors.unknownError": "An unexpected error occurred. Please try again.",
                "files.loadingFiles": "Loading files...",
                "files.noFilesYet": "No files yet",
                "files.uploadFilesHint": "Upload files to get started.",
                "files.nameColumn": "Name",
                "files.typeColumn": "Type",
                "files.actionsColumn": "Actions",
                "files.rename": "Rename",
                "files.delete": "Delete",
                "files.renameFile": "Rename File",
                "files.cancel": "Cancel",
                "files.myFiles": "My Files",
                "files.sharedLibrary": "Shared Library",
                "files.allFiles": "All Files",
                "files.signInRequired": "Sign in required",
                "files.signInToManage": "Please sign in to manage your files.",
                "files.chooseFiles": "Choose files",
                "files.dragDropFiles": "Drag & drop files here",
                "files.orClickBrowse": "or click to browse",
                "files.uploading": "Uploading...",
                "files.folders": "Folders",
                "files.newFolder": "New Folder",
                "files.folderActions": "Folder actions",
                "files.folderNamePlaceholder": "Folder name",
                "files.deleteFolderConfirm": "Delete this folder and all its contents?",
                "agentPlan.source": "Source:",
                "agentPlan.search": "Search:",
                "agentPlan.executionSteps": "Execution steps",
                "agentPlan.iterationSteps": "Iteration {{number}} Execution steps",
                "agentPlan.step": "Step",
                "agentPlan.details": "Details",
                "agentPlan.elapsedMs": "Elapsed MS",
                "agentPlan.noResults": "No results found",
            }
        }
    },
    interpolation: { escapeValue: false }
});

function AllProviders({ children }: { children: React.ReactNode }) {
    return (
        <MemoryRouter>
            <FluentProvider theme={webLightTheme}>
                <I18nextProvider i18n={i18nInstance}>{children}</I18nextProvider>
            </FluentProvider>
        </MemoryRouter>
    );
}

export function renderWithProviders(ui: React.ReactElement, options?: Omit<RenderOptions, "wrapper">) {
    return render(ui, { wrapper: AllProviders, ...options });
}
