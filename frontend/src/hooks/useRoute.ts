import { useEffect, useState } from "react";

export type Route = "overview" | "market" | "sources" | "account" | "admin";
const ROUTES: Route[] = ["overview", "market", "sources", "account", "admin"];

function read(): Route {
  const h = window.location.hash.replace(/^#\/?/, "");
  return (ROUTES as string[]).includes(h) ? (h as Route) : "overview";
}

/** Điều hướng bằng hash (#overview, #market): không cần cấu hình server. */
export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(read);
  useEffect(() => {
    const on = () => setRoute(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
