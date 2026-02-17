/**
 * Image viewer with sentence-level polygon highlighting.
 *
 * Renders an image and overlays normalised [0,1] polygons from Azure
 * Document Intelligence for pixel-accurate sentence highlighting.
 */
import { useRef, useState, useEffect, useCallback } from "react";
import { HighlightOverlay, SentenceHighlight } from "./HighlightOverlay";

interface Props {
    /** Image URL (blob URL or regular URL) */
    src: string;
    /** Alt text */
    alt?: string;
    /** Sentence highlights (normalised polygons) */
    highlights?: SentenceHighlight[];
    /** Max height for the image container */
    maxHeight?: string;
}

export const ImageHighlightViewer = ({ src, alt = "Citation Image", highlights = [], maxHeight = "810px" }: Props) => {
    const imgRef = useRef<HTMLImageElement>(null);
    const [dims, setDims] = useState<{ w: number; h: number }>({ w: 0, h: 0 });

    const updateDims = useCallback(() => {
        const img = imgRef.current;
        if (img && img.complete && img.naturalWidth > 0) {
            setDims({ w: img.clientWidth, h: img.clientHeight });
        }
    }, []);

    useEffect(() => {
        updateDims();
        window.addEventListener("resize", updateDims);
        return () => window.removeEventListener("resize", updateDims);
    }, [updateDims]);

    return (
        <div
            style={{
                position: "relative",
                display: "inline-block",
                maxHeight,
                overflow: "auto",
            }}
        >
            <img
                ref={imgRef}
                src={src}
                alt={alt}
                onLoad={updateDims}
                style={{ display: "block", maxWidth: "100%" }}
            />
            {dims.w > 0 && highlights.length > 0 && (
                <HighlightOverlay
                    highlights={highlights}
                    width={dims.w}
                    height={dims.h}
                />
            )}
        </div>
    );
};
