"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { History, LoaderCircle, MessageSquarePlus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type SessionSummary = {
  id: string;
  title: string;
  updated_at: number;
};

function timeAgo(epochSeconds: number) {
  const s = Math.max(1, Math.floor(Date.now() / 1000 - epochSeconds));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function ChatSessionsMenu({ projectId, chatId }: { projectId: string; chatId: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listChats(projectId);
      setSessions(res.chats || []);
    } catch (e: any) {
      setError(e?.message || "Failed to load sessions");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (!open) return;
    load();
  }, [open, load]);

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

  const remove = async (id: string) => {
    setDeleting(id);
    try {
      await api.deleteChat(id);
      setSessions((s) => s.filter((c) => c.id !== id));
      if (id === chatId) router.push(`/project/${projectId}/chat/${crypto.randomUUID()}`);
    } catch (e: any) {
      setError(e?.message || "Failed to delete session");
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-1.5 rounded-md border bg-background px-2.5 py-1.5 text-xs shadow-sm transition-colors hover:bg-muted",
          open && "bg-muted"
        )}
        title="Your sessions"
      >
        <History className="size-3.5" /> Sessions
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-72 overflow-hidden rounded-lg border bg-card shadow-lg">
          <div className="flex items-center justify-between border-b px-3 py-2">
            <span className="text-xs font-medium">Your sessions</span>
            <button
              onClick={() => router.push(`/project/${projectId}/chat/${crypto.randomUUID()}`)}
              className="flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <MessageSquarePlus className="size-3" /> New
            </button>
          </div>

          <div className="max-h-72 overflow-y-auto">
            {loading ? (
              <div className="flex items-center gap-2 px-3 py-4 text-xs text-muted-foreground">
                <LoaderCircle className="size-3.5 animate-spin" /> Loading…
              </div>
            ) : error ? (
              <p className="px-3 py-3 text-xs text-red-500">{error}</p>
            ) : sessions.length === 0 ? (
              <p className="px-3 py-4 text-xs text-muted-foreground">No saved sessions yet.</p>
            ) : (
              sessions.map((s) => (
                <div
                  key={s.id}
                  className={cn(
                    "group flex items-center gap-1 border-b px-3 py-2 last:border-0 hover:bg-muted/50",
                    s.id === chatId && "bg-primary/5"
                  )}
                >
                  <button
                    className="min-w-0 flex-1 text-left"
                    onClick={() => {
                      setOpen(false);
                      if (s.id !== chatId) router.push(`/project/${projectId}/chat/${s.id}`);
                    }}
                  >
                    <p className={cn("truncate text-sm", s.id === chatId ? "font-medium" : "")}>
                      {s.title || "New chat"}
                    </p>
                    <p className="text-[10px] text-muted-foreground">
                      {timeAgo(s.updated_at)} {s.id === chatId && "· current"}
                    </p>
                  </button>
                  <button
                    onClick={() => remove(s.id)}
                    disabled={deleting === s.id}
                    title="Delete session"
                    className="rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-red-500/10 hover:text-red-500 group-hover:opacity-100"
                  >
                    {deleting === s.id
                      ? <LoaderCircle className="size-3.5 animate-spin" />
                      : <Trash2 className="size-3.5" />}
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
