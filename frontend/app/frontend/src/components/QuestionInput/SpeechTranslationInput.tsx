/**
 * SpeechTranslationInput — Azure Speech SDK voice input with auto language detection + translation.
 *
 * Uses TranslationRecognizer to:
 * 1. Auto-detect the spoken language (from configured candidate list)
 * 2. Transcribe speech to text
 * 3. Translate to target language (default: English)
 *
 * Falls back to browser Web Speech API via SpeechInput if token fetch fails.
 */

import { useState, useRef, useCallback, useEffect } from "react";
import { Button, Tooltip, Badge } from "@fluentui/react-components";
import { Mic28Filled } from "@fluentui/react-icons";
import { useTranslation } from "react-i18next";

import styles from "./QuestionInput.module.css";
import { getSpeechTokenApi, SpeechTokenResponse } from "../../api/api";
import { SpeechInput } from "./SpeechInput";

interface Props {
    updateQuestion: (question: string) => void;
    onSpeechResult?: (info: { detectedLanguage: string; wasTranslated: boolean }) => void;
}

export const SpeechTranslationInput = ({ updateQuestion, onSpeechResult }: Props) => {
    const { t, i18n } = useTranslation();
    const [isRecording, setIsRecording] = useState(false);
    const [detectedLang, setDetectedLang] = useState<string | null>(null);
    const [sdkAvailable, setSdkAvailable] = useState<boolean | null>(null); // null = unknown
    const recognizerRef = useRef<any>(null);
    const tokenRef = useRef<SpeechTokenResponse | null>(null);

    // Determine the target translation language from the i18n locale (e.g. "en-US" → "en")
    const getTargetLang = useCallback(() => {
        const locale = i18n.language || "en";
        return locale.split("-")[0].toLowerCase();
    }, [i18n.language]);

    // Probe for token availability on mount
    useEffect(() => {
        let cancelled = false;
        getSpeechTokenApi().then(token => {
            if (!cancelled) {
                tokenRef.current = token;
                setSdkAvailable(token !== null);
            }
        });
        return () => { cancelled = true; };
    }, []);

    const startRecording = useCallback(async () => {
        // Lazy-load the Speech SDK to keep bundle small for non-users
        let sdk: typeof import("microsoft-cognitiveservices-speech-sdk");
        try {
            sdk = await import("microsoft-cognitiveservices-speech-sdk");
        } catch (err) {
            console.error("Failed to load Speech SDK", err);
            setSdkAvailable(false);
            return;
        }

        // Refresh token if needed
        let token = tokenRef.current;
        if (!token) {
            token = await getSpeechTokenApi();
            tokenRef.current = token;
        }
        if (!token) {
            setSdkAvailable(false);
            return;
        }

        try {
            const targetLang = getTargetLang();

            // Build SpeechTranslationConfig from auth token
            const translationConfig = sdk.SpeechTranslationConfig.fromAuthorizationToken(
                token.token,
                token.region
            );

            // Add the target translation language
            translationConfig.addTargetLanguage(targetLang);

            // Set up auto-detect source languages from server-provided list
            const autoDetectConfig = sdk.AutoDetectSourceLanguageConfig.fromLanguages(
                token.languages
            );

            // Use default microphone input
            const audioConfig = sdk.AudioConfig.fromDefaultMicrophoneInput();

            // Create TranslationRecognizer with auto language detection
            const recognizer = sdk.TranslationRecognizer.FromConfig(
                translationConfig,
                autoDetectConfig,
                audioConfig
            );

            recognizerRef.current = recognizer;
            setDetectedLang(null);
            setIsRecording(true);

            // Interim results — update the input field live
            recognizer.recognizing = (_sender: any, event: any) => {
                if (event.result.text) {
                    // Prefer the translated text for the input field
                    const translated = event.result.translations?.get(targetLang);
                    updateQuestion(translated || event.result.text);
                }
            };

            // Final result — set the translated text
            recognizer.recognized = (_sender: any, event: any) => {
                const reason = event.result.reason;
                if (reason === sdk.ResultReason.TranslatedSpeech) {
                    const translated = event.result.translations?.get(targetLang);
                    if (translated) {
                        updateQuestion(translated);
                    }

                    // Extract detected language from the result
                    const autoDetectResult = sdk.AutoDetectSourceLanguageResult.fromResult(event.result);
                    const lang = autoDetectResult?.language;
                    if (lang && lang !== "Unknown") {
                        const langCode = lang.split("-")[0];
                        setDetectedLang(langCode);
                        // Report speech metadata for dashboard stats
                        onSpeechResult?.({
                            detectedLanguage: langCode,
                            wasTranslated: langCode !== targetLang,
                        });
                    }
                } else if (reason === sdk.ResultReason.NoMatch) {
                    console.warn("Speech not recognized");
                }
            };

            recognizer.canceled = (_sender: any, event: any) => {
                console.warn("Speech recognition canceled:", event.errorDetails);
                stopRecording();
            };

            recognizer.sessionStopped = () => {
                stopRecording();
            };

            // Start continuous recognition
            recognizer.startContinuousRecognitionAsync(
                () => { /* started */ },
                (err: string) => {
                    console.error("Failed to start recognition:", err);
                    setIsRecording(false);
                }
            );
        } catch (err) {
            console.error("Speech translation setup failed:", err);
            setIsRecording(false);
        }
    }, [getTargetLang, updateQuestion]);

    const stopRecording = useCallback(() => {
        const recognizer = recognizerRef.current;
        if (recognizer) {
            recognizer.stopContinuousRecognitionAsync(
                () => {
                    recognizer.close();
                    recognizerRef.current = null;
                },
                (err: string) => {
                    console.error("Failed to stop recognition:", err);
                    recognizer.close();
                    recognizerRef.current = null;
                }
            );
        }
        setIsRecording(false);
    }, []);

    // Cleanup on unmount
    useEffect(() => {
        return () => {
            if (recognizerRef.current) {
                try { recognizerRef.current.close(); } catch { /* ignore */ }
            }
        };
    }, []);

    // Still checking or Azure not available → fall back to browser speech
    if (sdkAvailable === false) {
        return <SpeechInput updateQuestion={updateQuestion} />;
    }

    // Loading state — show nothing until we know
    if (sdkAvailable === null) {
        return null;
    }

    return (
        <>
            {!isRecording ? (
                <div className={styles.questionInputButtonsContainer}>
                    <Tooltip content={t("tooltips.askWithVoice")} relationship="label">
                        <Button
                            size="large"
                            icon={<Mic28Filled primaryFill="rgba(115, 118, 225, 1)" />}
                            onClick={startRecording}
                        />
                    </Tooltip>
                </div>
            ) : (
                <div className={styles.questionInputButtonsContainer} style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
                    {detectedLang && (
                        <Badge appearance="outline" color="informative" size="small">
                            {detectedLang}
                        </Badge>
                    )}
                    <Tooltip content={t("tooltips.stopRecording")} relationship="label">
                        <Button
                            size="large"
                            icon={<Mic28Filled primaryFill="rgba(250, 0, 0, 0.7)" />}
                            onClick={stopRecording}
                        />
                    </Tooltip>
                </div>
            )}
        </>
    );
};
