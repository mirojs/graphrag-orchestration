/**
 * Shared SVG overlay for drawing sentence-level polygon highlights.
 *
 * Polygons are expected in Azure DI normalized [0,1] coordinates:
 *   [x1, y1, x2, y2, x3, y3, x4, y4]
 *
 * The overlay stretches to fill its parent container and converts
 * normalised coords to percentages so highlights scale automatically.
 */
import { CSSProperties } from "react";

/** One sentence span with multi-polygon geometry (handles line-wrapping). */
export interface SentenceHighlight {
    text: string;
    page: number; // 1-indexed
    polygons: number[][]; // Each inner array = [x1,y1,...,x4,y4] in [0,1]
    confidence?: number;
}

interface Props {
    /** Sentence highlights to draw */
    highlights: SentenceHighlight[];
    /** Which page is currently visible (1-indexed). Only matching highlights are drawn. */
    visiblePage?: number;
    /** CSS width of the overlay container (must match the rendered page / image). */
    width: number;
    /** CSS height of the overlay container. */
    height: number;
    /** Optional extra CSS styles for the container. */
    style?: CSSProperties;
}

/**
 * Convert a flat [x1,y1,x2,y2,x3,y3,x4,y4] array to SVG `points` string
 * by scaling normalised coords to pixel values.
 */
const toSvgPoints = (polygon: number[], w: number, h: number): string => {
    const pts: string[] = [];
    for (let i = 0; i < polygon.length - 1; i += 2) {
        const px = polygon[i] * w;
        const py = polygon[i + 1] * h;
        pts.push(`${px},${py}`);
    }
    return pts.join(" ");
};

export const HighlightOverlay = ({ highlights, visiblePage, width, height, style }: Props) => {
    if (!highlights.length || width <= 0 || height <= 0) return null;

    const filtered = visiblePage != null ? highlights.filter(h => h.page === visiblePage) : highlights;
    if (!filtered.length) return null;

    return (
        <svg
            width={width}
            height={height}
            viewBox={`0 0 ${width} ${height}`}
            style={{
                position: "absolute",
                top: 0,
                left: 0,
                pointerEvents: "none",
                ...style,
            }}
        >
            {filtered.flatMap((h, hIdx) =>
                h.polygons.map((poly, pIdx) => (
                    <polygon
                        key={`${hIdx}-${pIdx}`}
                        points={toSvgPoints(poly, width, height)}
                        fill="rgba(255, 235, 59, 0.35)"
                        stroke="rgba(255, 193, 7, 0.85)"
                        strokeWidth={1.5}
                    />
                ))
            )}
        </svg>
    );
};
