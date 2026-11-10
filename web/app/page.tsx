"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BookOpen, Database, FileText, Layers3, Plus, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ThemeToggle } from "@/components/theme-toggle";
import { api, type IndexInfo } from "@/lib/api";
import { cn } from "@/lib/utils";

function makeChatHref() {
  const id = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
  return `/project/default/chat/${id}`;
}

export default function Home() {
  const [info, setInfo] = useState<IndexInfo | null>(null);
  const [config, setConfig] = useState<any>(null);
  const [status, setStatus] = useState<"loading" | "ok" | "no-index" | "offline">("loading");
  const [newChatHref, setNewChatHref] = useState("/project/default/chat/new");

  useEffect(() => {
    setNewChatHref(makeChatHref());
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const c = await api.config();
        setConfig(c);
      } catch {}
      try {
        const i = await api.indexInfo();
        setInfo(i);
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

          <Link href={newChatHref} className="group">
            <Card className="flex h-full min-h-[220px] flex-col transition-all hover:-translate-y-0.5 hover:border-foreground/20 hover:shadow-md">
              <CardHeader>
                <div className="mb-1 flex items-center justify-between">
                  <div className="flex size-8 items-center justify-center rounded-md bg-muted text-muted-foreground">
                    <Layers3 className="size-4" />
                  </div>
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    <Database className="size-3" />
                    Qdrant
                  </span>
                </div>
                <CardTitle className="text-lg">Default library</CardTitle>
                <CardDescription className="line-clamp-2">
                  {config?.pdf_dir ? `PDF folder: ${config.pdf_dir}` : "Configure a PDF folder, index it, and chat with citations."}
                </CardDescription>
              </CardHeader>
              <CardContent className="mt-auto">
                {info ? (
                  <div className="flex items-center gap-4 text-sm text-muted-foreground">
                    <span className="flex items-center gap-1.5"><FileText className="size-4" />{info.documents} papers</span>
                    <span>{info.chunks.toLocaleString()} chunks</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <RefreshCw className="size-3.5" />
                    {status === "offline" ? "Start backend to connect" : status === "no-index" ? "Build index to begin" : "Loading…"}
                  </div>
                )}
              </CardContent>
            </Card>
          </Link>
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
