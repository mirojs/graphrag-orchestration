import styles from "../../pages/files/Files.module.css";

interface FileToolbarProps {
    fileCount: number;
    selectedCount: number;
    searchQuery: string;
    onSearchChange: (q: string) => void;
    sortBy: "name" | "ext";
    sortAsc: boolean;
    onSortChange: (by: "name" | "ext") => void;
    onSelectAll: () => void;
    onSelectNone: () => void;
    onDeleteSelected: () => void;
    onRefresh: () => void;
}

export const FileToolbar = ({
    fileCount,
    selectedCount,
    searchQuery,
    onSearchChange,
    sortBy,
    sortAsc,
    onSortChange,
    onSelectAll,
    onSelectNone,
    onDeleteSelected,
    onRefresh,
}: FileToolbarProps) => {
    const arrow = sortAsc ? "↑" : "↓";

    return (
        <div className={styles.toolbar}>
            <input
                className={styles.searchBox}
                type="text"
                placeholder="Search files..."
                value={searchQuery}
                onChange={(e) => onSearchChange(e.target.value)}
            />

            <span className={styles.toolbarMeta}>
                {fileCount} file{fileCount !== 1 ? "s" : ""}
                {selectedCount > 0 && ` · ${selectedCount} selected`}
            </span>

            <button
                className={`${styles.toolbarBtn} ${sortBy === "name" ? styles.sortActive : ""}`}
                onClick={() => onSortChange("name")}
                title="Sort by name"
            >
                Name {sortBy === "name" ? arrow : ""}
            </button>

            <button
                className={`${styles.toolbarBtn} ${sortBy === "ext" ? styles.sortActive : ""}`}
                onClick={() => onSortChange("ext")}
                title="Sort by type"
            >
                Type {sortBy === "ext" ? arrow : ""}
            </button>

            {selectedCount > 0 ? (
                <>
                    <button className={styles.toolbarBtn} onClick={onSelectNone}>
                        Deselect
                    </button>
                    <button className={styles.toolbarBtnDanger} onClick={onDeleteSelected}>
                        🗑️ Delete ({selectedCount})
                    </button>
                </>
            ) : (
                <button className={styles.toolbarBtn} onClick={onSelectAll}>
                    Select All
                </button>
            )}

            <button className={styles.toolbarBtn} onClick={onRefresh} title="Refresh">
                🔄
            </button>
        </div>
    );
};
