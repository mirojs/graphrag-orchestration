import DOMPurify from "dompurify";

import { DataPoints, StructuredCitation } from "../../api";
import { parseSupportingContentItem } from "./SupportingContentParser";

import styles from "./SupportingContent.module.css";

interface Props {
    supportingContent?: DataPoints;
}

const StructuredCitationItem = ({ citation, index }: { citation: StructuredCitation; index: number }) => {
    const title = citation.document_title || citation.source || `Citation ${index + 1}`;
    const sectionLabel = citation.section_path && citation.section_path !== "General" ? citation.section_path : null;
    const pageLabel = citation.page_number != null ? `Page ${citation.page_number}` : null;
    const locationParts = [pageLabel, sectionLabel].filter(Boolean).join(" · ");
    const text = DOMPurify.sanitize(citation.sentence_text || citation.text_preview || "");

    return (
        <li className={styles.supportingContentItem}>
            <h4 className={styles.supportingContentItemHeader}>
                {citation.document_url ? (
                    <a href={citation.document_url} target="_blank" rel="noreferrer">
                        {title}
                    </a>
                ) : (
                    title
                )}
                {citation.citation && <span style={{ marginLeft: 6, opacity: 0.6, fontSize: "0.85em" }}>{citation.citation}</span>}
            </h4>
            {locationParts && (
                <p style={{ margin: "2px 0 4px", fontSize: "0.85em", color: "#666" }}>
                    {locationParts}
                    {citation.document_id && <span style={{ marginLeft: 8, opacity: 0.5, fontSize: "0.9em" }}>ID: {citation.document_id}</span>}
                </p>
            )}
            {text && <p className={styles.supportingContentItemText} dangerouslySetInnerHTML={{ __html: text }} />}
        </li>
    );
};

export const SupportingContent = ({ supportingContent }: Props) => {
    const structuredItems = supportingContent?.structured_citations ?? [];
    const textItems = supportingContent?.text ?? [];
    const imageItems = supportingContent?.images ?? [];
    const webItems = supportingContent?.external_results_metadata ?? [];

    // Prefer structured citations when available (from GraphRAG backend)
    const useStructured = structuredItems.length > 0;

    return (
        <ul className={styles.supportingContentNavList}>
            {useStructured
                ? structuredItems.map((c, ind) => (
                      <StructuredCitationItem citation={c} index={ind} key={`structured-citation-${ind}`} />
                  ))
                : textItems.map((c, ind) => {
                      const parsed = parseSupportingContentItem(c);
                      return (
                          <li className={styles.supportingContentItem} key={`supporting-content-text-${ind}`}>
                              <h4 className={styles.supportingContentItemHeader}>{parsed.title}</h4>
                              <p className={styles.supportingContentItemText} dangerouslySetInnerHTML={{ __html: parsed.content }} />
                          </li>
                      );
                  })}
            {imageItems?.map((img, ind) => {
                return (
                    <li className={styles.supportingContentItem} key={`supporting-content-image-${ind}`}>
                        <img className={styles.supportingContentItemImage} src={img} alt="Supporting content" />
                    </li>
                );
            })}
            {webItems.map((item, ind) => (
                <li className={styles.supportingContentItem} key={`supporting-content-web-${item.id ?? ind}`}>
                    {item.url ? (
                        <h4 className={styles.supportingContentItemHeader}>
                            <a href={item.url} target="_blank" rel="noreferrer">
                                {item.title ?? item.url}
                            </a>
                        </h4>
                    ) : (
                        <h4 className={styles.supportingContentItemHeader}>{item.title ?? "Web result"}</h4>
                    )}
                </li>
            ))}
        </ul>
    );
};
