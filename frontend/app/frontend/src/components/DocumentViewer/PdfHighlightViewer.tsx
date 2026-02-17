/**
 * PDF viewer using pdf.js with sentence-level polygon highlighting.
 *
 * Renders a single page (or all pages) from a PDF blob URL, then overlays
 * normalised [0,1] polygons from Azure Document Intelligence for
 * pixel-accurate sentence highlighting.
 */
import { useEffect, useRef, useState, useCallback } from "react";
import * as pdfjsLib from "pdfjs-dist";
import { HighlightOverlay, SentenceHighlight } from "./HighlightOverlay";

// Configure pdf.js worker via CDN (avoids Vite bundling issues)
pdfjsLib.GlobalWorkerOptions.workerSrc = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjsLib.version}/pdf.worker.min.mjs`;

interface Props {
    /** Blob URL or regular URL pointing to the PDF */
    src: string;
    /** Page to navigate to (1-indexed). Defaults to 1 or the first highlighted page. */
    targetPage?: number;
    /** Sentence highlights (normalised polygons) */
    highlights?: SentenceHighlight[];
    /** CSS height for the viewer container */
    height?: string;
}

export const PdfHighlightViewer = ({ src, targetPage, highlights = [], height = "810px" }: Props) => {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const [pageNum, setPageNum] = useState(targetPage ?? 1);
    const [numPages, setNumPages] = useState(0);
    const [canvasDims, setCanvasDims] = useState<{ w: number; h: number }>({ w: 0, h: 0 });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const pdfDocRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null);

    // Determine initial page from highlights if not explicitly set
    useEffect(() => {
        if (!targetPage && highlights.length > 0) {
            const firstPage = highlights[0].page;
            if (firstPage > 0) setPageNum(firstPage);
        }
    }, [targetPage, highlights]);

    // Load the PDF document once
    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError(null);

        const loadPdf = async () => {
            try {
                // Convert blob URL to ArrayBuffer for pdf.js
                const response = await fetch(src);
                const arrayBuffer = await response.arrayBuffer();
                const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
                if (cancelled) return;
                pdfDocRef.current = pdf;
                setNumPages(pdf.numPages);
                setLoading(false);
            } catch (e) {
                if (!cancelled) {
                    console.error("Failed to load PDF:", e);
                    setError("Failed to load PDF document");
                    setLoading(false);
                }
            }
        };

        loadPdf();
        return () => {
            cancelled = true;
        };
    }, [src]);

    // Render the current page
    const renderPage = useCallback(async () => {
        const pdf = pdfDocRef.current;
        const canvas = canvasRef.current;
        if (!pdf || !canvas) return;

        try {
            const page = await pdf.getPage(pageNum);
            const containerWidth = containerRef.current?.clientWidth ?? 800;

            // Scale to fit container width
            const unscaledViewport = page.getViewport({ scale: 1 });
            const scale = containerWidth / unscaledViewport.width;
            const viewport = page.getViewport({ scale });

            canvas.width = viewport.width;
            canvas.height = viewport.height;

            const ctx = canvas.getContext("2d");
            if (!ctx) return;

            await page.render({ canvasContext: ctx, viewport }).promise;
            setCanvasDims({ w: viewport.width, h: viewport.height });
        } catch (e) {
            console.error("Failed to render page:", e);
        }
    }, [pageNum]);

    useEffect(() => {
        if (!loading && pdfDocRef.current) {
            renderPage();
        }
    }, [loading, pageNum, renderPage]);

    const goToPrev = () => setPageNum(p => Math.max(1, p - 1));
    const goToNext = () => setPageNum(p => Math.min(numPages, p + 1));

    if (error) {
        return <div style={{ padding: 16, color: "#c00" }}>{error}</div>;
    }

    return (
        <div
            ref={containerRef}
            style={{
                height,
                overflow: "auto",
                position: "relative",
                background: "#525659",
            }}
        >
            {/* Page navigation toolbar */}
            {numPages > 1 && (
                <div
                    style={{
                        position: "sticky",
                        top: 0,
                        zIndex: 10,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        gap: 8,
                        padding: "6px 12px",
                        background: "rgba(50,50,50,0.9)",
                        color: "#fff",
                        fontSize: 13,
                    }}
                >
                    <button onClick={goToPrev} disabled={pageNum <= 1} style={navBtnStyle}>
                        ◀
                    </button>
                    <span>
                        Page {pageNum} / {numPages}
                    </span>
                    <button onClick={goToNext} disabled={pageNum >= numPages} style={navBtnStyle}>
                        ▶
                    </button>
                    {highlights.length > 0 && (
                        <span style={{ marginLeft: 12, opacity: 0.7, fontSize: 11 }}>
                            {highlights.filter(h => h.page === pageNum).length} highlight(s) on this page
                        </span>
                    )}
                </div>
            )}

            {loading && (
                <div style={{ padding: 32, color: "#aaa", textAlign: "center" }}>Loading PDF…</div>
            )}

            {/* Canvas + highlight overlay */}
            <div style={{ position: "relative", display: "inline-block" }}>
                <canvas ref={canvasRef} style={{ display: "block" }} />
                {canvasDims.w > 0 && (
                    <HighlightOverlay
                        highlights={highlights}
                        visiblePage={pageNum}
                        width={canvasDims.w}
                        height={canvasDims.h}
                    />
                )}
            </div>
        </div>
    );
};

const navBtnStyle: React.CSSProperties = {
    background: "transparent",
    border: "1px solid rgba(255,255,255,0.4)",
    color: "#fff",
    borderRadius: 4,
    padding: "2px 10px",
    cursor: "pointer",
    fontSize: 13,
};
