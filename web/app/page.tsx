"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, Ellipsis, MessageSquarePlus, Pencil, Plus, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ThemeToggle } from "@/components/theme-toggle";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/use-auth";
import { UserMenu } from "@/components/user-menu";
import { cn } from "@/lib/utils";

function makeChatHref() {
  const id = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
  return `/project/default/chat/${id}`;
}

function timeAgo(epochSeconds: number) {
  const s = Math.max(1, Math.floor(Date.now() / 1000 - epochSeconds));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function CardMenu({
  onOpen,
  onDelete,
}: {
  onOpen: () => void;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
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

  return (
    <div className="relative" ref={ref} onClick={(e) => e.preventDefault()}>
      <button
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen((v) => !v); }}
        className={cn(
          "flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
          open && "bg-muted text-foreground"
        )}
        title="Session actions"
      >
        <Ellipsis className="size-4" />
      </button>
      {open && (
        <div className="absolute right-1 top-full z-50 mt-1 w-40 overflow-hidden rounded-lg border bg-card text-sm shadow-lg">
          <button
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(false); onOpen(); }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-muted"
          >
            <Pencil className="size-3.5" /> Open chat
          </button>
          <button
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(false); onDelete(); }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-red-600 hover:bg-red-500/10 dark:text-red-400"
          >
            <Trash2 className="size-3.5" /> Delete
          </button>
        </div>
      )}
    </div>
  );
}

export default function Home() {
  const { user, ready: authReady } = useRequireAuth();
  const [status, setStatus] = useState<"loading" | "ok" | "no-index" | "offline">("loading");
  const [newChatHref, setNewChatHref] = useState("/project/default/chat/new");
  const [sessions, setSessions] = useState<{ id: string; title: string; updated_at: number }[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadSessions = useCallback(async () => {
    if (!authReady) return;
    try {
      const res = await api.listChats("default");
      setSessions(res.chats || []);
    } catch {}
  }, [authReady]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  const deleteSession = async (id: string) => {
    setDeletingId(id);
    try {
      await api.deleteChat(id);
      setSessions((s) => s.filter((c) => c.id !== id));
    } catch {}
    setDeletingId(null);
  };

  useEffect(() => {
    setNewChatHref(makeChatHref());
  }, []);

  useEffect(() => {
    (async () => {
      try {
        await api.indexInfo();
        setStatus("ok");
      } catch {
        try {
          await api.health();
          setStatus("no-index");
        } catch {
          setStatus("offline");
        }
      }
    })();
  }, []);

  return (
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-neutral-100 via-background to-background dark:from-neutral-900">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-8">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg border bg-card shadow-sm">
            <BookOpen className="size-4" />
          </div>
          <div>
            <p className="text-sm font-semibold tracking-tight">Relevantr</p>
            <p className="text-xs text-muted-foreground">Scientific PDF workspace</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          {user && <UserMenu user={user} />}
          <Link href={newChatHref} className={cn(buttonVariants())}>
            <Plus className="size-4" />
            New chat
          </Link>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl px-6 pb-16">
        <div className="mb-8 flex items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">Projects</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Each chat has a unique URL. Open the library to index papers and ask questions.
            </p>
          </div>
          {status === "ok" && <Badge variant="success">Backend connected</Badge>}
          {status === "no-index" && <Badge variant="warning">No index yet</Badge>}
          {status === "offline" && <Badge variant="danger">Backend offline</Badge>}
          {status === "loading" && <Badge variant="secondary">Connecting…</Badge>}
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Link href={newChatHref} className="group">
            <Card className="flex h-full min-h-[220px] flex-col items-center justify-center border-dashed bg-transparent text-muted-foreground transition-colors hover:border-foreground/30 hover:bg-card hover:text-foreground">
              <div className="flex size-11 items-center justify-center rounded-full border bg-background shadow-sm transition-transform group-hover:scale-105">
                <Plus className="size-5" />
              </div>
              <p className="mt-3 font-medium text-foreground">New chat</p>
              <p className="mt-1 max-w-[220px] text-center text-sm">
                Start a new conversation in the library (gets a unique URL).
              </p>
            </Card>
          </Link>

          {sessions.map((s) => (
            <Link key={s.id} href={`/project/default/chat/${s.id}`} className="group">
              <Card className="flex h-full min-h-[220px] flex-col transition-all hover:-translate-y-0.5 hover:border-foreground/20 hover:shadow-md">
                <CardHeader>
                  <div className="mb-1 flex items-center justify-between">
                    <div className="flex size-8 items-center justify-center rounded-md bg-muted text-muted-foreground">
                      <MessageSquarePlus className="size-4" />
                    </div>
                    <CardMenu
                      onOpen={() => (window.location.href = `/project/default/chat/${s.id}`)}
                      onDelete={() => deleteSession(s.id)}
                    />
                  </div>
                  <CardTitle className="line-clamp-2 text-base">{s.title || "New chat"}</CardTitle>
                  <CardDescription className="line-clamp-1">
                    {deletingId === s.id ? "Deleting…" : timeAgo(s.updated_at)}
                  </CardDescription>
                </CardHeader>
                <CardContent className="mt-auto">
                  <p className="font-mono text-[10px] text-muted-foreground">{s.id.slice(0, 8)}</p>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>

        {status === "offline" && (
          <div className="mt-6 rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            <p className="font-medium text-foreground">Backend not reachable</p>
            <p className="mt-1">Run FastAPI on port 8000 (e.g. <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">uvicorn server.app.main:app --reload --port 8000</code>) and Qdrant, then refresh.</p>
          </div>
        )}
      </main>
    </div>
  );
}
