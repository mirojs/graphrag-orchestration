import { Button } from "@fluentui/react-components";
import { ErrorCircle24Regular } from "@fluentui/react-icons";
import { useTranslation } from "react-i18next";

import styles from "./Answer.module.css";

interface Props {
    error: string;
    onRetry: () => void;
}

export const AnswerError = ({ error, onRetry }: Props) => {
    const { t } = useTranslation();

    return (
        <div className={styles.answerContainer} style={{ display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
            <ErrorCircle24Regular aria-hidden="true" aria-label="Error icon" primaryFill="red" />

            <div style={{ flexGrow: 1 }}>
                <p className={styles.answerText}>{error}</p>
            </div>

            <Button appearance="primary" className={styles.retryButton} onClick={onRetry}>
                {t("errors.retry")}
            </Button>
        </div>
    );
};
