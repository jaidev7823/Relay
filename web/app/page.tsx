"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, Ellipsis, FolderOpen, LoaderCircle, Pencil, Plus, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ThemeToggle } from "@/components/theme-toggle";
import { api, type Project } from "@/lib/api";
import { useRequireAuth } from "@/lib/use-auth";
import { UserMenu } from "@/components/user-menu";
import { cn } from "@/lib/utils";

function makeChatId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
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
  const router = useRouter();
  const { user, ready: authReady } = useRequireAuth();
  const [status, setStatus] = useState<"loading" | "ok" | "offline">("loading");
  const [projects, setProjects] = useState<Project[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const [adding, setAdding] = useState<string | null>(null); // upload progress text

  const loadProjects = useCallback(async () => {
    if (!authReady) return;
    try {
      const res = await api.projects();
      setProjects(res.projects || []);
    } catch {}
  }, [authReady]);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const deleteProject = async (id: string) => {
    setDeletingId(id);
    try {
      await api.deleteProject(id);
      setProjects((p) => p.filter((x) => x.id !== id));
    } catch {}
    setDeletingId(null);
  };

  const addSources = async (fileList: FileList | null) => {
    const files = Array.from(fileList || []).filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    if (!files.length) { setAdding(null); return; }
    setAdding("Creating library…");
    try {
      // Derive a name from the folder picked, else the first file.
      const rel = (files[0] as File & { webkitRelativePath?: string }).webkitRelativePath || "";
      const folderName = rel.includes("/") ? rel.split("/")[0] : files[0].name.replace(/\.pdf$/i, "");
      const project = await api.createProject(folderName);
      setAdding("Uploading " + files.length + " file" + (files.length === 1 ? "" : "s") + "…");
      await api.uploadFiles(project.id, files);
      router.push(`/project/${project.id}/chat/${makeChatId()}`);
    } catch (e: any) {
      setAdding(null);
      alert(e?.message || "Failed to add sources");
      loadProjects();
    }
  };

  useEffect(() => {
    (async () => {
      try {
        await api.health();
        setStatus("ok");
      } catch {
        setStatus("offline");
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
          <button onClick={() => fileInputRef.current?.click()} className={cn(buttonVariants())}>
            <Plus className="size-4" />
            Add sources
          </button>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl px-6 pb-16">
        <div className="mb-8 flex items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">Libraries</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Pick a folder or files — they get embedded and you get a chat with its own URL.
            </p>
          </div>
          {status === "ok" && <Badge variant="success">Backend connected</Badge>}
          {status === "offline" && <Badge variant="danger">Backend offline</Badge>}
          {status === "loading" && <Badge variant="secondary">Connecting…</Badge>}
        </div>

        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,application/pdf"
          className="hidden"
          onChange={(e) => { addSources(e.target.files); e.target.value = ""; }}
        />
        <input
          ref={folderInputRef}
          type="file"
          multiple
          className="hidden"
          {...{ webkitdirectory: "", directory: "" }}
          onChange={(e) => { addSources(e.target.files); e.target.value = ""; }}
        />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <button
            onClick={() => fileInputRef.current?.click()}
            className="group text-left"
            disabled={adding !== null}
          >
            <Card className="flex h-full min-h-[220px] flex-col items-center justify-center border-dashed bg-transparent text-muted-foreground transition-colors hover:border-foreground/30 hover:bg-card hover:text-foreground">
              <div className="flex size-11 items-center justify-center rounded-full border bg-background shadow-sm transition-transform group-hover:scale-105">
                <Plus className="size-5" />
              </div>
              {adding ? (
                <>
                  <p className="mt-3 flex items-center gap-2 font-medium text-foreground">
                    <LoaderCircle className="size-4 animate-spin" /> {adding}
                  </p>
                  <p className="mt-1 max-w-[220px] text-center text-sm">Hold tight — embedding starts automatically.</p>
                </>
              ) : (
                <>
                  <p className="mt-3 font-medium text-foreground">Add sources</p>
                  <p className="mt-1 max-w-[220px] text-center text-sm">
                    Pick PDF files to create a new library.
                    <span
                      role="link"
                      className="mt-1 inline-flex items-center gap-1 underline underline-offset-2"
                      onClick={(e) => { e.stopPropagation(); folderInputRef.current?.click(); }}
                    >
                      <FolderOpen className="size-3" /> or choose a folder
                    </span>
                  </p>
                </>
              )}
            </Card>
          </button>

          {projects.map((p) => (
            <Link key={p.id} href={`/project/${p.id}/chat/${makeChatId()}`} className="group" onClick={() => {}}>
              <Card className="flex h-full min-h-[220px] flex-col transition-all hover:-translate-y-0.5 hover:border-foreground/20 hover:shadow-md">
                <CardHeader>
                  <div className="mb-1 flex items-center justify-between">
                    <div className="flex size-8 items-center justify-center rounded-md bg-muted text-muted-foreground">
                      <BookOpen className="size-4" />
                    </div>
                    <CardMenu
                      onOpen={() => router.push(`/project/${p.id}/chat/${makeChatId()}`)}
                      onDelete={() => deleteProject(p.id)}
                    />
                  </div>
                  <CardTitle className="line-clamp-2 text-base">{p.name}</CardTitle>
                  <CardDescription className="line-clamp-1">
                    {deletingId === p.id ? "Deleting…" : timeAgo(p.created_at)}
                  </CardDescription>
                </CardHeader>
                <CardContent className="mt-auto">
                  <p className="font-mono text-[10px] text-muted-foreground">{p.id.slice(0, 8)} · {p.qdrant_collection}</p>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>

        {projects.length === 0 && adding === null && status === "ok" && (
          <p className="mt-4 text-xs text-muted-foreground">No libraries yet — add a folder or files above.</p>
        )}

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
