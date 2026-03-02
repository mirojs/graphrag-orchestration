import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// Polyfill Element.scrollIntoView for jsdom
Element.prototype.scrollIntoView = vi.fn();

// Mock authConfig module — it performs top-level await fetch("/auth_setup")
// which fails in jsdom (no base URL for relative paths).
vi.mock("../authConfig", () => ({
    useLogin: false,
    requireAccessControl: false,
    enableUnauthenticatedAccess: true,
    requireLogin: false,
    isUsingAppServicesLogin: false,
    msalConfig: { auth: { clientId: "", authority: "", redirectUri: "/", postLogoutRedirectUri: "/" }, cache: { cacheLocation: "sessionStorage", storeAuthStateInCookie: false } },
    loginRequest: { scopes: [] },
    getRedirectUri: () => "/",
    appServicesLogout: () => {},
    checkLoggedIn: async () => false,
    getToken: async () => undefined,
    getUsername: async () => null,
    getTokenClaims: async () => undefined
}));
