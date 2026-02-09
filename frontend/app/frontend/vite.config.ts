import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [react()],
    resolve: {
        preserveSymlinks: true
    },
    build: {
        outDir: "dist",
        emptyOutDir: true,
        sourcemap: true,
        rollupOptions: {
            output: {
                manualChunks: id => {
                    if (id.includes("@fluentui/react-icons")) {
                        return "fluentui-icons";
                    } else if (id.includes("@fluentui/react")) {
                        return "fluentui-react";
                    } else if (id.includes("node_modules")) {
                        return "vendor";
                    }
                }
            }
        },
        target: "esnext"
    },
    server: {
        proxy: {
            // All requests now go to FastAPI (consolidated backend)
            "/content/": "http://localhost:8000",
            "/auth_setup": "http://localhost:8000",
            "/redirect": "http://localhost:8000",
            "/.auth/me": "http://localhost:8000",
            "/chat": "http://localhost:8000",
            "/speech": "http://localhost:8000",
            "/config": "http://localhost:8000",
            "/upload": "http://localhost:8000",
            "/delete_uploaded": "http://localhost:8000",
            "/delete_uploaded_bulk": "http://localhost:8000",
            "/list_uploaded": "http://localhost:8000",
            "/rename_uploaded": "http://localhost:8000",
            "/move_uploaded": "http://localhost:8000",
            "/copy_uploaded": "http://localhost:8000",
            "/chat_history": "http://localhost:8000",
            "/file_metadata": "http://localhost:8000"
        }
    }
});
