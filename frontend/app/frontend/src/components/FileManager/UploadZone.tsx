import { useCallback, useRef, useState, DragEvent, ChangeEvent } from "react";
import styles from "../../pages/files/Files.module.css";

interface UploadZoneProps {
    onUpload: (files: File[]) => void;
    uploading: boolean;
    progress: number;
    acceptedTypes: string;
}

export const UploadZone = ({ onUpload, uploading, progress, acceptedTypes }: UploadZoneProps) => {
    const [dragOver, setDragOver] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);

    const handleDragOver = useCallback((e: DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setDragOver(true);
    }, []);

    const handleDragLeave = useCallback((e: DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setDragOver(false);
    }, []);

    const handleDrop = useCallback(
        (e: DragEvent) => {
            e.preventDefault();
            e.stopPropagation();
            setDragOver(false);
            const dropped: File[] = Array.from(e.dataTransfer.files);
            if (dropped.length > 0) onUpload(dropped);
        },
        [onUpload]
    );

    const handleBrowse = () => inputRef.current?.click();

    const handleInputChange = (e: ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files.length > 0) {
            onUpload(Array.from(e.target.files));
            e.target.value = ""; // allow re-selecting same file
        }
    };

    const zoneClass = [
        styles.uploadZone,
        dragOver ? styles.uploadZoneDragOver : "",
        uploading ? styles.uploadZoneUploading : "",
    ]
        .filter(Boolean)
        .join(" ");

    return (
        <div
            className={zoneClass}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={handleBrowse}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === "Enter" && handleBrowse()}
        >
            <span className={styles.uploadIcon}>{uploading ? "⏳" : "📤"}</span>
            {uploading ? (
                <>
                    <p className={styles.uploadText}>Uploading...</p>
                    <div className={styles.progressBarOuter}>
                        <div className={styles.progressBarInner} style={{ width: `${progress}%` }} />
                    </div>
                    <p className={styles.progressLabel}>{progress}%</p>
                </>
            ) : (
                <>
                    <p className={styles.uploadText}>Drag & drop files here</p>
                    <p className={styles.uploadTextSub}>or click to browse</p>
                    <button className={styles.uploadBrowseBtn} onClick={(e) => { e.stopPropagation(); handleBrowse(); }}>
                        Choose Files
                    </button>
                </>
            )}
            <input
                ref={inputRef}
                type="file"
                multiple
                accept={acceptedTypes}
                style={{ display: "none" }}
                onChange={handleInputChange}
            />
        </div>
    );
};
