import { useMsal } from "@azure/msal-react";
import { Tab, TabList, SelectTabData, SelectTabEvent } from "@fluentui/react-components";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { ChatAppResponse, fetchWithAuthRetry, getHeaders } from "../../api";
import { StructuredCitation } from "../../api/models";
import { getToken, useLogin } from "../../authConfig";
import { PdfHighlightViewer, ImageHighlightViewer, SentenceHighlight } from "../DocumentViewer";
import { MarkdownViewer } from "../MarkdownViewer";
import styles from "./AnalysisPanel.module.css";
import { AnalysisPanelTabs } from "./AnalysisPanelTabs";

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

/**
 * Detect whether polygon coordinates are raw DI values (inches) rather than
 * normalised [0,1].  Any coordinate > 1.0 is a clear signal — normalised
 * values never exceed 1.
 */
function needsNormalization(polygon: number[]): boolean {
    return polygon.some(v => v > 1.0);
}

/**
 * Normalise a raw-inch polygon to [0,1] using page dimensions.
 * Falls back to standard US-Letter (8.5 × 11 in) if dims are unavailable.
 */
function normalizePolygon(polygon: number[], pageW: number, pageH: number): number[] {
    const out: number[] = [];
    for (let i = 0; i < polygon.length; i++) {
        out.push(i % 2 === 0 ? polygon[i] / pageW : polygon[i] / pageH);
    }
    return out;
}

/**
 * Build SentenceHighlight[] from structured citations by extracting polygon data
 * from the `sentences` array on each citation.
 *
 * Handles two polygon formats that may arrive from the backend:
 *   1. Flat arrays (paragraph sentences): [[x1,y1,x2,y2,...], ...]
 *   2. Legacy dict format (pre-fix table rows): [{"page":N,"polygon":[...]}, ...]
 *
 * Also handles pre-fix data where coordinates are raw DI inches instead of
 * normalised [0,1] — detected via any coord > 1.0, then normalised using
 * page_dimensions from the citation (or US-Letter fallback).
 */
function buildHighlights(citations: StructuredCitation[]): SentenceHighlight[] {
    const highlights: SentenceHighlight[] = [];
    for (const sc of citations) {
        // Resolve page dimensions for raw-inch → [0,1] normalisation
        const dims = sc.page_dimensions;
        // Find first page dim entry (or fallback to US-Letter 8.5×11 inches)
        const pageDim = Array.isArray(dims) && dims.length > 0 ? dims[0] : null;
        const pageW: number = (pageDim?.width as number) || 8.5;
        const pageH: number = (pageDim?.height as number) || 11;

        // If the structured citation has sentence-level polygon data, use it.
        const sentenceSpans = sc.sentences;
        if (Array.isArray(sentenceSpans)) {
            for (const span of sentenceSpans) {
                const rawPolygons: any[] = span.polygons ?? [];
                if (rawPolygons.length === 0) continue;

                // Extract: accept both flat number arrays and {polygon:[...]} dicts
                let polygons: number[][] = rawPolygons
                    .map((p: any) => (Array.isArray(p) ? p : Array.isArray(p?.polygon) ? p.polygon : null))
                    .filter((p: number[] | null): p is number[] => p != null && p.length >= 8);

                // Auto-normalise raw-inch coordinates from pre-fix indexed data
                if (polygons.length > 0 && needsNormalization(polygons[0])) {
                    // Use per-span page to pick correct dimensions if available
                    const spanPage = span.page ?? sc.page_number ?? 1;
                    const spanDim = Array.isArray(dims) ? dims.find((d: any) => d.page === spanPage || d.page_number === spanPage) : null;
                    const w = (spanDim?.width as number) || pageW;
                    const h = (spanDim?.height as number) || pageH;
                    polygons = polygons.map(poly => normalizePolygon(poly, w, h));
                }

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
            const response = await fetchWithAuthRetry(urlNoHash, {
                method: "GET",
                headers: await getHeaders(token),
            });
            if (!response.ok) {
                console.error(`Citation fetch failed: ${response.status} ${response.statusText}`);
                setCitationBlob("");
                setCitation("");
                return;
            }
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
            return <img src={citation} className={styles.citationImg} alt={t("analysis.citationImage")} />;
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
                <div className={styles.sentencePanelHeader}>{t("analysis.citedSentences")}</div>
                {activeCitationObj.map((sc, idx) => (
                    <div key={idx} className={styles.sentenceItem}>
                        {sc.page_number != null && (
                            <span className={styles.sentencePageBadge}>{t("analysis.page", { number: sc.page_number })}</span>
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
        <div className={className}>
            <TabList selectedValue={activeTab} onTabSelect={(_ev: SelectTabEvent, data: SelectTabData) => onActiveTabChanged(data.value as AnalysisPanelTabs)}>
                <Tab value={AnalysisPanelTabs.CitationTab} disabled={isDisabledCitationTab}>
                    {t("headerTexts.citation")}
                </Tab>
            </TabList>
            <div>
                {activeTab === AnalysisPanelTabs.CitationTab && (
                    <>
                        {renderSentenceTextPanel()}
                        {renderFileViewer()}
                    </>
                )}
            </div>
        </div>
    );
};
