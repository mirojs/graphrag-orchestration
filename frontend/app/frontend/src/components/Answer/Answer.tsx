import { useMemo, useState } from "react";
import { Button } from "@fluentui/react-components";
import { Copy24Regular, Checkmark24Regular } from "@fluentui/react-icons";
import { useTranslation } from "react-i18next";
import DOMPurify from "dompurify";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";

import styles from "./Answer.module.css";
import { ChatAppResponse, getCitationFilePath, SpeechConfig } from "../../api";
import { parseAnswerToHtml } from "./AnswerParser";
import { AnswerIcon } from "./AnswerIcon";
import { SpeechOutputBrowser } from "./SpeechOutputBrowser";
import { SpeechOutputAzure } from "./SpeechOutputAzure";

interface Props {
    answer: ChatAppResponse;
    index: number;
    speechConfig: SpeechConfig;
    isSelected?: boolean;
    isStreaming: boolean;
    onCitationClicked: (filePath: string) => void;
    onFollowupQuestionClicked?: (question: string) => void;
    showFollowupQuestions?: boolean;
    showSpeechOutputBrowser?: boolean;
    showSpeechOutputAzure?: boolean;
}

export const Answer = ({
    answer,
    index,
    speechConfig,
    isSelected,
    isStreaming,
    onCitationClicked,
    onFollowupQuestionClicked,
    showFollowupQuestions,
    showSpeechOutputAzure,
    showSpeechOutputBrowser
}: Props) => {
    const followupQuestions = answer.context?.followup_questions;
    const parsedAnswer = useMemo(() => parseAnswerToHtml(answer, isStreaming, onCitationClicked), [answer, isStreaming, onCitationClicked]);
    const { t } = useTranslation();
    // DOMPurify sanitized copy — used only for clipboard copy and speech output.
    // NOT used for ReactMarkdown because DOMPurify's HTML parser collapses \n
    // to spaces between inline elements, breaking markdown list rendering.
    const sanitizedAnswerHtml = DOMPurify.sanitize(parsedAnswer.answerHtml);
    // For ReactMarkdown: use raw answerHtml (newlines preserved).
    // Only HTML present is our own citation <span>s from renderToStaticMarkup().
    const markdownReady = parsedAnswer.answerHtml
        .replace(/^• /gm, "- ")
        .replace(/([^\n])\n(#{1,6} )/g, "$1\n\n$2")
        .replace(/([^\n])\n([-*] |\d+[.)]\s)/g, "$1\n\n$2");
    const [copied, setCopied] = useState(false);

    const handleCopy = () => {
        const tempElement = document.createElement("div");
        tempElement.innerHTML = sanitizedAnswerHtml;
        tempElement.querySelectorAll("sup").forEach(node => node.remove());
        tempElement.querySelectorAll(".citationStepBadge").forEach(node => node.remove());
        const textToCopy = tempElement.textContent ?? "";

        navigator.clipboard
            .writeText(textToCopy)
            .then(() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
            })
            .catch(err => console.error("Failed to copy text: ", err));
    };

    return (
        <div
            className={`${styles.answerContainer} ${isSelected ? styles.selected : ""}`}
            style={{ display: "flex", flexDirection: "column", justifyContent: "space-between" }}
        >
            <div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <AnswerIcon />
                    <div>
                        <Button
                            appearance="transparent"
                            style={{ color: "black" }}
                            icon={copied ? <Checkmark24Regular /> : <Copy24Regular />}
                            title={copied ? t("tooltips.copied") : t("tooltips.copy")}
                            aria-label={copied ? t("tooltips.copied") : t("tooltips.copy")}
                            onClick={handleCopy}
                        />
                        {showSpeechOutputAzure && (
                            <SpeechOutputAzure answer={sanitizedAnswerHtml} index={index} speechConfig={speechConfig} isStreaming={isStreaming} />
                        )}
                        {showSpeechOutputBrowser && <SpeechOutputBrowser answer={sanitizedAnswerHtml} />}
                    </div>
                </div>
            </div>

            <div style={{ flexGrow: 1 }}>
                <div
                    className={styles.answerText}
                    onClick={e => {
                        const target = (e.target as HTMLElement).closest<HTMLElement>("[data-citation-path]");
                        if (target) {
                            e.preventDefault();
                            const path = target.getAttribute("data-citation-path");
                            const ck = target.getAttribute("data-citation-key");
                            if (path) onCitationClicked(ck ? `${path}#ck=${encodeURIComponent(ck)}` : path);
                        }
                    }}
                >
                    <ReactMarkdown children={markdownReady} rehypePlugins={[rehypeRaw]} remarkPlugins={[remarkGfm]} />
                </div>
            </div>

            {(() => {
                // Build citation list from structured_citations (sentence-level)
                const structuredCitations = answer.context?.data_points?.structured_citations || [];
                if (!structuredCitations.length) return null;

                // De-duplicate by citation key or chunk_id (sentence-level), not document title
                const seen = new Set<string>();
                const uniqueCitations = structuredCitations.filter(sc => {
                    const key = sc.citation || sc.chunk_id || `${sc.document_title}-${sc.page_number}-${sc.sentence_text || sc.text_preview || ""}`;
                    if (!key || seen.has(key)) return false;
                    seen.add(key);
                    return true;
                });
                if (!uniqueCitations.length) return null;

                return (
                    <div>
                        <div className={styles.citationLearnMore}>{t("citationWithColon")}</div>
                        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                            {uniqueCitations.map((sc, idx) => {
                                const rawName = sc.document_title || sc.source || "Unknown";
                                const docName = (() => { try { return decodeURIComponent(rawName); } catch { return rawName; } })();
                                let path = getCitationFilePath(docName, sc.document_url);
                                const hashParts: string[] = [];
                                if (sc.page_number) hashParts.push(`page=${sc.page_number}`);
                                if (sc.citation) hashParts.push(`ck=${encodeURIComponent(sc.citation)}`);
                                if (hashParts.length) path += `#${hashParts.join("&")}`;
                                const pageInfo = sc.page_number ? ` p.${sc.page_number}` : "";
                                const sectionInfo = sc.section_path && sc.section_path !== "General" ? ` §${sc.section_path}` : "";
                                const sentencePreview = sc.sentence_text || sc.text_preview || "";
                                const truncated = sentencePreview.length > 80 ? sentencePreview.substring(0, 77) + "…" : sentencePreview;
                                const locationParts = [docName, pageInfo, sectionInfo].filter(Boolean).join(",");
                                const label = truncated ? `${truncated} (${locationParts})` : `${docName}${pageInfo}`;

                                return (
                                    <span key={`${sc.citation || docName}-${idx}`} className={styles.citationEntry}>
                                        <a
                                            className={styles.citation}
                                            title={sentencePreview || docName}
                                            onClick={e => {
                                                e.preventDefault();
                                                onCitationClicked(path);
                                            }}
                                        >
                                            {`${idx + 1}. ${label}`}
                                        </a>
                                    </span>
                                );
                            })}
                        </div>
                    </div>
                );
            })()}

            {!!followupQuestions?.length && showFollowupQuestions && onFollowupQuestionClicked && (
                <div>
                    <div
                        style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}
                        className={`${!!(answer.context?.data_points?.structured_citations?.length) ? styles.followupQuestionsList : ""}`}
                    >
                        <span className={styles.followupQuestionLearnMore}>{t("followupQuestions")}</span>
                        {followupQuestions.map((x, i) => {
                            return (
                                <a key={i} className={styles.followupQuestion} title={x} onClick={() => onFollowupQuestionClicked(x)}>
                                    {`${x}`}
                                </a>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
};
