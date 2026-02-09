import { useState, useEffect, useRef } from "react";
import styles from "../../pages/files/Files.module.css";

interface RenameDialogProps {
    currentName: string;
    onRename: (newName: string) => void;
    onDismiss: () => void;
}

export const RenameDialog = ({ currentName, onRename, onDismiss }: RenameDialogProps) => {
    const [value, setValue] = useState(currentName);
    const inputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        // Select filename without extension
        const dotIdx = currentName.lastIndexOf(".");
        inputRef.current?.focus();
        if (dotIdx > 0) {
            inputRef.current?.setSelectionRange(0, dotIdx);
        } else {
            inputRef.current?.select();
        }
    }, [currentName]);

    const handleSubmit = () => {
        const trimmed = value.trim();
        if (trimmed && trimmed !== currentName) {
            onRename(trimmed);
        } else {
            onDismiss();
        }
    };

    return (
        <div className={styles.overlay} onClick={onDismiss}>
            <div className={styles.dialog} onClick={(e) => e.stopPropagation()}>
                <h3>Rename File</h3>
                <input
                    ref={inputRef}
                    className={styles.dialogInput}
                    type="text"
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === "Enter") handleSubmit();
                        if (e.key === "Escape") onDismiss();
                    }}
                />
                <div className={styles.dialogActions}>
                    <button className={styles.dialogBtn} onClick={onDismiss}>
                        Cancel
                    </button>
                    <button className={styles.dialogBtnPrimary} onClick={handleSubmit}>
                        Rename
                    </button>
                </div>
            </div>
        </div>
    );
};
