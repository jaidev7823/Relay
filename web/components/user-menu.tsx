"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, LogOut, UserCircle2 } from "lucide-react";
import { api } from "@/lib/api";
import type { CurrentUser } from "@/lib/use-auth";
import { cn } from "@/lib/utils";

export function UserMenu({ user }: { user: CurrentUser }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  const logout = async () => {
    setLoggingOut(true);
    await api.logout().catch(() => {});
    router.replace("/login");
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-2 rounded-md border bg-background px-2.5 py-1.5 text-sm shadow-sm transition-colors hover:bg-muted",
          open && "bg-muted"
        )}
        title="Account"
      >
        <UserCircle2 className="size-4 text-muted-foreground" />
        <span className="hidden max-w-[140px] truncate sm:inline">
          Hi, <span className="font-medium">{user.username}</span>
        </span>
        <ChevronDown className={cn("size-3.5 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-52 overflow-hidden rounded-lg border bg-card shadow-lg">
          <div className="border-b px-3 py-2.5">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Signed in as</p>
            <p className="mt-0.5 truncate text-sm font-medium">{user.username}</p>
          </div>
          <button
            onClick={logout}
            disabled={loggingOut}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-red-600 transition-colors hover:bg-red-500/10 dark:text-red-400"
          >
            <LogOut className="size-3.5" /> Log out
          </button>
        </div>
      )}
    </div>
  );
}
