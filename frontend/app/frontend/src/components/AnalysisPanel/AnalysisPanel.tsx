import { useMsal } from "@azure/msal-react";
import { Pivot, PivotItem } from "@fluentui/react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { ChatAppResponse, getHeaders } from "../../api";
import { StructuredCitation } from "../../api/models";
import { getToken, useLogin } from "../../authConfig";
import { PdfHighlightViewer, ImageHighlightViewer, SentenceHighlight } from "../DocumentViewer";
import { MarkdownViewer } from "../MarkdownViewer";
import { SupportingContent } from "../SupportingContent";
import styles from "./AnalysisPanel.module.css";
import { AnalysisPanelTabs } from "./AnalysisPanelTabs";
import { ThoughtProcess } from "./ThoughtProcess";

interface Props {
    className: string;
    activeTab: AnalysisPanelTabs;
    onActiveTabChanged: (tab: AnalysisPanelTabs) => void;
    activeCitation: string | undefined;
    /** Structured citation metadata for the active citation (for highlighting) */
    activeCitationObj?: StructuredCitation[];
    citationHeight: string;
    answer: ChatAppResponse;
    onCitationClicked?: (citationFilePath: string) => void;
}

const pivotItemDisabledStyle = { disabled: true, style: { color: "grey" } };

/**
 * Build SentenceHighlight[] from structured citations by extracting polygon data
 * from the `sentences` array on each citation.
 */
function buildHighlights(citations: StructuredCitation[]): SentenceHighlight[] {
    const highlights: SentenceHighlight[] = [];
    for (const sc of citations) {
        // If the structured citation has sentence-level polygon data, use it.
        const sentenceSpans = sc.sentences;
        if (Array.isArray(sentenceSpans)) {
            for (const span of sentenceSpans) {
                const polygons: number[][] = span.polygons ?? [];
                if (polygons.length > 0) {
                    highlights.push({
                        text: span.text ?? sc.sentence_text ?? sc.text_preview ?? "",
                        page: span.page ?? sc.page_number ?? 1,
                        polygons,
                        confidence: span.confidence,
                    });
                }
            }
        }
        // Fallback: if no sentence spans but we have sentence_text, add a text-only highlight
        // (no polygon overlay, but the viewer can still jump to the page)
    }
    return highlights;
}

export const AnalysisPanel = ({
    answer,
    activeTab,
    activeCitation,
    activeCitationObj,
    citationHeight,
    className,
    onActiveTabChanged,
    onCitationClicked,
}: Props) => {
    const isDisabledThoughtProcessTab: boolean = !answer.context.thoughts;
    const dataPoints = answer.context.data_points;
    const hasSupportingContent = Boolean(
        dataPoints &&
            ((dataPoints.text && dataPoints.text.length > 0) ||
                (dataPoints.images && dataPoints.images.length > 0) ||
                (dataPoints.external_results_metadata && dataPoints.external_results_metadata.length > 0))
    );
    const isDisabledSupportingContentTab: boolean = !hasSupportingContent;
    const isDisabledCitationTab: boolean = !activeCitation;
    const [citation, setCitation] = useState("");
    const [citationBlob, setCitationBlob] = useState<string>(""); // raw blob URL (no hash)

    const client = useLogin ? useMsal().instance : undefined;
    const { t } = useTranslation();

    // Pre-compute sentence highlights from structured citation data
    const highlights = useMemo<SentenceHighlight[]>(
        () => (activeCitationObj ? buildHighlights(activeCitationObj) : []),
        [activeCitationObj]
    );

    // Determine the target page from structured citation or URL hash
    const targetPage = useMemo<number | undefined>(() => {
        // From structured citation metadata
        if (activeCitationObj && activeCitationObj.length > 0) {
            const p = activeCitationObj[0].page_number;
            if (p != null && p > 0) return p;
        }
        // From URL hash (#page=N)
        if (activeCitation) {
            const hashMatch = activeCitation.match(/#page=(\d+)/);
            if (hashMatch) return parseInt(hashMatch[1], 10);
        }
        return undefined;
    }, [activeCitationObj, activeCitation]);

    const fetchCitation = async () => {
        const token = client ? await getToken(client) : undefined;
        if (activeCitation) {
            // Strip hash from URL for fetching
            const urlNoHash = activeCitation.split("#")[0];
            const originalHash = activeCitation.includes("#") ? activeCitation.split("#")[1] : "";
            const response = await fetch(urlNoHash, {
                method: "GET",
                headers: await getHeaders(token),
            });
            const citationContent = await response.blob();
            const blobUrl = URL.createObjectURL(citationContent);
            setCitationBlob(blobUrl);
            // For iframe/legacy viewers, add hash back
            setCitation(originalHash ? blobUrl + "#" + originalHash : blobUrl);
        }
    };
    useEffect(() => {
        fetchCitation();
    }, [activeCitation]);

    /** Detect file extension from activeCitation URL (before hash) */
    const fileExtension = useMemo(() => {
        if (!activeCitation) return "";
        const pathPart = activeCitation.split("#")[0].split("?")[0];
        return pathPart.split(".").pop()?.toLowerCase() ?? "";
    }, [activeCitation]);

    /** Whether we have polygon-based highlights to show */
    const hasPolygonHighlights = highlights.some(h => h.polygons.length > 0);

    const renderFileViewer = () => {
        if (!activeCitation) return null;

        // PDF with polygon highlights → use pdf.js viewer
        if ((fileExtension === "pdf" || !fileExtension) && hasPolygonHighlights && citationBlob) {
            return (
                <PdfHighlightViewer
                    src={citationBlob}
                    targetPage={targetPage}
                    highlights={highlights}
                    height={citationHeight}
                />
            );
        }

        // Image formats with highlights → use image viewer with overlay
        if (["png", "jpg", "jpeg", "tiff", "tif", "bmp"].includes(fileExtension) && citationBlob) {
            return (
                <ImageHighlightViewer
                    src={citationBlob}
                    highlights={hasPolygonHighlights ? highlights : []}
                    maxHeight={citationHeight}
                />
            );
        }

        // PNG without highlights → simple image
        if (fileExtension === "png") {
            return <img src={citation} className={styles.citationImg} alt="Citation Image" />;
        }

        // Markdown
        if (fileExtension === "md") {
            return <MarkdownViewer src={activeCitation} />;
        }

        // Default: iframe (works for PDF without highlights, Office formats, etc.)
        return <iframe title="Citation" src={citation} width="100%" height={citationHeight} />;
    };

    // Sentence text panel for non-PDF/non-image formats (show cited text alongside iframe)
    const renderSentenceTextPanel = () => {
        if (!activeCitationObj || activeCitationObj.length === 0) return null;
        // Only show for formats without polygon overlays
        if (hasPolygonHighlights && (fileExtension === "pdf" || ["png", "jpg", "jpeg", "tiff", "tif", "bmp"].includes(fileExtension))) return null;

        return (
            <div className={styles.sentencePanel}>
                <div className={styles.sentencePanelHeader}>Cited Sentences</div>
                {activeCitationObj.map((sc, idx) => (
                    <div key={idx} className={styles.sentenceItem}>
                        {sc.page_number != null && (
                            <span className={styles.sentencePageBadge}>Page {sc.page_number}</span>
                        )}
                        <span className={styles.sentenceText}>
                            {sc.sentence_text || sc.text_preview || ""}
                        </span>
                    </div>
                ))}
            </div>
        );
    };

    return (
        <Pivot
            className={className}
            selectedKey={activeTab}
            onLinkClick={pivotItem => pivotItem && onActiveTabChanged(pivotItem.props.itemKey! as AnalysisPanelTabs)}
        >
            <PivotItem
                itemKey={AnalysisPanelTabs.ThoughtProcessTab}
                headerText={t("headerTexts.thoughtProcess")}
                headerButtonProps={isDisabledThoughtProcessTab ? pivotItemDisabledStyle : undefined}
            >
                <ThoughtProcess thoughts={answer.context.thoughts || []} onCitationClicked={onCitationClicked} />
            </PivotItem>
            <PivotItem
                itemKey={AnalysisPanelTabs.SupportingContentTab}
                headerText={t("headerTexts.supportingContent")}
                headerButtonProps={isDisabledSupportingContentTab ? pivotItemDisabledStyle : undefined}
            >
                <SupportingContent supportingContent={answer.context.data_points} />
            </PivotItem>
            <PivotItem
                itemKey={AnalysisPanelTabs.CitationTab}
                headerText={t("headerTexts.citation")}
                headerButtonProps={isDisabledCitationTab ? pivotItemDisabledStyle : undefined}
            >
                {renderSentenceTextPanel()}
                {renderFileViewer()}
            </PivotItem>
        </Pivot>
    );
};
