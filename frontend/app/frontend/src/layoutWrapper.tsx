import { useEffect, useRef, useState } from "react";
import { useMsal } from "@azure/msal-react";
import { InteractionStatus } from "@azure/msal-browser";
import { useLogin, checkLoggedIn, loginRequest, getRedirectUri } from "./authConfig";
import { LoginContext } from "./loginContext";
import Layout from "./pages/layout/Layout";

const LayoutWrapper = () => {
    const [loggedIn, setLoggedIn] = useState(false);
    if (useLogin) {
        const { instance, inProgress } = useMsal();
        // Keep track of the mounted state to avoid setting state in an unmounted component
        const mounted = useRef<boolean>(true);
        useEffect(() => {
            mounted.current = true;
            checkLoggedIn(instance)
                .then(isLoggedIn => {
                    if (mounted.current) {
                        setLoggedIn(isLoggedIn);
                        // Auto-redirect to Entra sign-in if not logged in and no interaction is in progress
                        if (!isLoggedIn && inProgress === InteractionStatus.None) {
                            instance.loginRedirect({
                                ...loginRequest,
                                redirectUri: getRedirectUri()
                            });
                        }
                    }
                })
                .catch(e => {
                    console.error("checkLoggedIn failed", e);
                });
            return () => {
                mounted.current = false;
            };
        }, [instance, inProgress]);

        return (
            <LoginContext.Provider value={{ loggedIn, setLoggedIn }}>
                <Layout />
            </LoginContext.Provider>
        );
    } else {
        return (
            <LoginContext.Provider
                value={{
                    loggedIn,
                    setLoggedIn
                }}
            >
                <Layout />
            </LoginContext.Provider>
        );
    }
};

export default LayoutWrapper;
