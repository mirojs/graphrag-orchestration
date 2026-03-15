import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useFileBlob } from "../../hooks/useFileBlob";
import { PdfHighlightViewer } from "../DocumentViewer/PdfHighlightViewer";
import DOMPurify from "dompurify";
import styles from "./FilePreviewPanel.module.css";

interface Props {
    filename: string;
    /** All filenames in the current list — enables prev/next navigation */
    allFiles: string[];
    /** Active folder name — needed to resolve blob path */
    folder?: string;
    onDismiss: () => void;
    /** Navigate to a different file */
    onNavigate: (filename: string) => void;
}

type FileCategory = "pdf" | "image" | "html" | "docx" | "xlsx" | "pptx" | "text" | "unknown";

function getCategory(filename: string): FileCategory {
    const ext = filename.split(".").pop()?.toLowerCase() || "";
    if (ext === "pdf") return "pdf";
    if (["png", "jpg", "jpeg", "bmp", "tiff", "tif", "gif", "webp"].includes(ext)) return "image";
    if (["html", "htm"].includes(ext)) return "html";
    if (ext === "docx") return "docx";
    if (ext === "xlsx" || ext === "xls") return "xlsx";
    if (ext === "pptx" || ext === "ppt") return "pptx";
    if (["txt", "csv", "json", "xml", "md", "log"].includes(ext)) return "text";
    return "unknown";
}

export const FilePreviewPanel = ({ filename, allFiles, folder, onDismiss, onNavigate }: Props) => {
    const { t } = useTranslation();
    const { blobUrl, rawBytes, contentType, loading, error } = useFileBlob(filename, folder);
    const category = useMemo(() => getCategory(filename), [filename]);

    // Zoom state
    const [zoom, setZoom] = useState(1);

    // Reset zoom on file change
    useEffect(() => { setZoom(1); }, [filename]);

    // File navigation
    const currentIndex = allFiles.indexOf(filename);
    const hasPrev = currentIndex > 0;
    const hasNext = currentIndex < allFiles.length - 1;
    const goPrev = () => hasPrev && onNavigate(allFiles[currentIndex - 1]);
    const goNext = () => hasNext && onNavigate(allFiles[currentIndex + 1]);

    // Keyboard shortcuts
    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if (e.key === "Escape") onDismiss();
        };
        window.addEventListener("keydown", handler);
        return () => window.removeEventListener("keydown", handler);
    });

    // Scroll wheel zoom
    const handleWheel = useCallback((e: React.WheelEvent) => {
        if (e.ctrlKey || e.metaKey) {
            e.preventDefault();
            const delta = e.deltaY > 0 ? -0.15 : 0.15;
            setZoom(z => Math.max(0.25, Math.min(5, z + delta)));
        }
    }, []);

    const zoomPercent = Math.round(zoom * 100);

    return (
        <div className={styles.panel}>
            {/* Header */}
            <div className={styles.header}>
                <span className={styles.filename} title={filename}>{filename}</span>
                <button className={styles.headerBtn} onClick={onDismiss} title={t("preview.close")}>✕</button>
            </div>

            {/* Toolbar */}
            <div className={styles.toolbar}>
                <button className={styles.toolBtn} onClick={goPrev} disabled={!hasPrev} title={t("preview.prev")}>◀</button>
                <span className={styles.navInfo}>{currentIndex + 1} / {allFiles.length}</span>
                <button className={styles.toolBtn} onClick={goNext} disabled={!hasNext} title={t("preview.next")}>▶</button>
                <span className={styles.sep} />
                {(category === "image" || category === "pdf") && (
                    <>
                        <button className={styles.toolBtn} onClick={() => setZoom(z => Math.max(0.25, z - 0.25))}>−</button>
                        <span className={styles.zoomLevel}>{zoomPercent}%</span>
                        <button className={styles.toolBtn} onClick={() => setZoom(z => Math.min(5, z + 0.25))}>+</button>
                        <button className={styles.toolBtn} onClick={() => setZoom(1)} title={t("preview.fitWidth")}>⊡</button>
                        <span className={styles.sep} />
                    </>
                )}
            </div>

            {/* Content */}
            <div className={styles.content} onWheel={handleWheel}>
                {loading && (
                    <div className={styles.stateCard}>
                        <div className={styles.spinner} />
                        <p>{t("preview.loading")}</p>
                    </div>
                )}

                {error && (
                    <div className={styles.stateCard}>
                        <p className={styles.errorText}>{t("preview.error")}</p>
                        <p>{error}</p>
                    </div>
                )}

                {!loading && !error && blobUrl && (
                    <div className={styles.viewerWrap} style={{ transform: `scale(${zoom})`, transformOrigin: "top center" }}>
                        <ContentRenderer
                            category={category}
                            blobUrl={blobUrl}
                            rawBytes={rawBytes}
                            contentType={contentType}
                            filename={filename}
                        />
                    </div>
                )}
            </div>
        </div>
    );
};

/* ---- Format-specific renderers ---- */

interface RendererProps {
    category: FileCategory;
    blobUrl: string;
    rawBytes: ArrayBuffer | null;
    contentType: string | null;
    filename: string;
}

const ContentRenderer = ({ category, blobUrl, rawBytes, contentType, filename }: RendererProps) => {
    switch (category) {
        case "pdf":
            return <PdfHighlightViewer src={blobUrl} highlights={[]} height="100%" />;
        case "image":
            return <ImageRenderer blobUrl={blobUrl} filename={filename} />;
        case "html":
            return <HtmlRenderer rawBytes={rawBytes} />;
        case "docx":
            return <DocxRenderer rawBytes={rawBytes} />;
        case "xlsx":
            return <XlsxRenderer rawBytes={rawBytes} />;
        case "pptx":
        case "text":
            return <TextRenderer rawBytes={rawBytes} />;
        default:
            return null;
    }
};

/* Image */
const ImageRenderer = ({ blobUrl, filename }: { blobUrl: string; filename: string }) => (
    <img src={blobUrl} alt={filename} className={styles.previewImage} draggable={false} />
);

/* HTML */
const HtmlRenderer = ({ rawBytes }: { rawBytes: ArrayBuffer | null }) => {
    const html = useMemo(() => {
        if (!rawBytes) return "";
        const text = new TextDecoder().decode(rawBytes);
        return DOMPurify.sanitize(text, { WHOLE_DOCUMENT: true, ADD_TAGS: ["style"] });
    }, [rawBytes]);

    return <iframe srcDoc={html} className={styles.htmlFrame} sandbox="allow-same-origin" title="HTML Preview" />;
};

/* Plain text */
const TextRenderer = ({ rawBytes }: { rawBytes: ArrayBuffer | null }) => {
    const text = useMemo(() => {
        if (!rawBytes) return "";
        return new TextDecoder().decode(rawBytes);
    }, [rawBytes]);

    return (
        <div className={styles.textWrap}>
            <pre>{text}</pre>
        </div>
    );
};

/* DOCX via mammoth (lazy-loaded) */
const DocxRenderer = ({ rawBytes }: { rawBytes: ArrayBuffer | null }) => {
    const { t } = useTranslation();
    const [html, setHtml] = useState<string | null>(null);
    const [err, setErr] = useState<string | null>(null);

    useEffect(() => {
        if (!rawBytes) return;
        let cancelled = false;

        (async () => {
            try {
                const mammoth = await import("mammoth");
                const result = await mammoth.convertToHtml({ arrayBuffer: rawBytes });
                if (!cancelled) {
                    setHtml(DOMPurify.sanitize(result.value, { WHOLE_DOCUMENT: true, ADD_TAGS: ["style"] }));
                }
            } catch (e: any) {
                if (!cancelled) setErr(e.message || "Failed to render DOCX");
            }
        })();

        return () => { cancelled = true; };
    }, [rawBytes]);

    if (err) return <div className={styles.stateCard}><p className={styles.errorText}>{t("preview.error")}</p><p>{err}</p></div>;
    if (!html) return <div className={styles.stateCard}><div className={styles.spinner} /><p>{t("preview.rendering")}</p></div>;
    return <iframe srcDoc={html} className={styles.htmlFrame} sandbox="allow-same-origin" title="DOCX Preview" />;
};

/* XLSX via SheetJS (lazy-loaded) */
const XlsxRenderer = ({ rawBytes }: { rawBytes: ArrayBuffer | null }) => {
    const { t } = useTranslation();
    const [tableHtml, setTableHtml] = useState<string | null>(null);
    const [err, setErr] = useState<string | null>(null);

    useEffect(() => {
        if (!rawBytes) return;
        let cancelled = false;

        (async () => {
            try {
                const XLSX = await import("xlsx");
                const wb = XLSX.read(rawBytes, { type: "array" });
                const firstSheet = wb.Sheets[wb.SheetNames[0]];
                const html = XLSX.utils.sheet_to_html(firstSheet);
                if (!cancelled) setTableHtml(html);
            } catch (e: any) {
                if (!cancelled) setErr(e.message || "Failed to render spreadsheet");
            }
        })();

        return () => { cancelled = true; };
    }, [rawBytes]);

    if (err) return <div className={styles.stateCard}><p className={styles.errorText}>{t("preview.error")}</p><p>{err}</p></div>;
    if (!tableHtml) return <div className={styles.stateCard}><div className={styles.spinner} /><p>{t("preview.rendering")}</p></div>;
    return <div className={styles.xlsxWrapper} dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(tableHtml) }} />;
};

