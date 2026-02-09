import styles from "../../pages/files/Files.module.css";

interface ToastProps {
    type: "success" | "error" | "info";
    text: string;
    onDismiss: () => void;
}

const TYPE_CLASS: Record<string, string> = {
    success: styles.toastSuccess,
    error: styles.toastError,
    info: styles.toastInfo,
};

const TYPE_ICON: Record<string, string> = {
    success: "✅",
    error: "❌",
    info: "ℹ️",
};

export const Toast = ({ type, text, onDismiss }: ToastProps) => (
    <div className={`${styles.toast} ${TYPE_CLASS[type] || ""}`}>
        <span>{TYPE_ICON[type]}</span>
        <span>{text}</span>
        <button className={styles.toastDismiss} onClick={onDismiss}>
            ✕
        </button>
    </div>
);
