/**
 * Test utilities: render wrapper with FluentUI + i18n providers.
 */
import React from "react";
import { render, RenderOptions } from "@testing-library/react";
import { FluentProvider, webLightTheme } from "@fluentui/react-components";
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
                "history.openChatHistory": "Open chat history",
                "labels.closeButton": "Close",
                "tooltips.submitQuestion": "Submit question",
                retry: "Retry"
            }
        }
    },
    interpolation: { escapeValue: false }
});

function AllProviders({ children }: { children: React.ReactNode }) {
    return (
        <FluentProvider theme={webLightTheme}>
            <I18nextProvider i18n={i18nInstance}>{children}</I18nextProvider>
        </FluentProvider>
    );
}

export function renderWithProviders(ui: React.ReactElement, options?: Omit<RenderOptions, "wrapper">) {
    return render(ui, { wrapper: AllProviders, ...options });
}
