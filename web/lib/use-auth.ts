"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "./api";

export type CurrentUser = { id: string; username: string };

/**
 * Checks the session with the backend and redirects to /login when
 * unauthenticated. Returns the user while the page is allowed to render.
 */
export function useRequireAuth(): { user: CurrentUser | null; ready: boolean } {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.me();
        if (!cancelled) {
          setUser(res.user);
          setReady(true);
        }
      } catch (e: any) {
        if (!cancelled && e?.status === 401) {
          router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`);
        } else if (!cancelled) {
          // backend offline: let the page render its own error UI
          setReady(true);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [router]);

  return { user, ready };
}
