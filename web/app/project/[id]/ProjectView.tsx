"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const PdfPageViewer = dynamic(
  () => import("@/components/pdf-page-viewer").then((m) => m.PdfPageViewer),
  { ssr: false, loading: () => <div className="py-8 text-center text-sm text-muted-foreground">Loading viewer…</div> }
);
import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  FileText,
  LoaderCircle,
  MessageSquarePlus,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings2,
  Sparkles,
  LogOut,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { SettingsDialog } from "@/components/settings-dialog";
import { ThemeToggle } from "@/components/theme-toggle";
import { api, type Doc, type IndexInfo, type Job } from "@/lib/api";
import { useRequireAuth } from "@/lib/use-auth";
import { loadChat, saveChat, type ChatMessage, type ChatSource } from "@/lib/chat-store";
import { cn } from "@/lib/utils";

function SourceStateIcon({ state }: { state: Doc["state"] }) {
  if (state === "ready") return <CircleCheck className="size-4 text-emerald-500" />;
  if (state === "embedding") return <LoaderCircle className="size-4 animate-spin text-amber-500" />;
  if (state === "new") return <CircleDashed className="size-4 text-sky-500" />;
  return <CircleAlert className="size-4 text-red-500" />;
}

function stateLabel(source: Doc) {
  if (source.state === "ready") return `${source.chunks ?? 0} chunks`;
  if (source.state === "embedding") return "Embedding…";
  if (source.state === "new") return "New, not embedded";
  return "Failed";
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
        h1: ({ children }) => <h1 className="mb-2 mt-3 first:mt-0 text-base font-semibold">{children}</h1>,
        h2: ({ children }) => <h2 className="mb-2 mt-3 first:mt-0 text-sm font-semibold">{children}</h2>,
        h3: ({ children }) => <h3 className="mb-1 mt-2 first:mt-0 text-sm font-medium">{children}</h3>,
        ul: ({ children }) => <ul className="mb-2 ml-4 list-disc space-y-1 last:mb-0">{children}</ul>,
        ol: ({ children }) => <ol className="mb-2 ml-4 list-decimal space-y-1 last:mb-0">{children}</ol>,
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
        blockquote: ({ children }) => (
          <blockquote className="my-2 border-l-2 border-border pl-3 italic text-muted-foreground">{children}</blockquote>
        ),
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noreferrer" className="underline underline-offset-2 hover:text-foreground">
            {children}
          </a>
        ),
        code: ({ className, children, ...props }) => {
          const isBlock = /language-/.test(className || "");
          if (isBlock) {
            return (
              <code className={cn("block overflow-x-auto font-mono text-xs", className)} {...props}>
                {children}
              </code>
            );
          }
          return (
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]" {...props}>
              {children}
            </code>
          );
        },
        pre: ({ children }) => (
          <pre className="my-2 overflow-x-auto rounded-md border bg-muted/50 p-3 text-xs last:mb-0">{children}</pre>
        ),
        table: ({ children }) => (
          <div className="my-2 overflow-x-auto last:mb-0">
            <table className="w-full border-collapse text-xs">{children}</table>
          </div>
        ),
        th: ({ children }) => <th className="border border-border bg-muted/50 px-2 py-1 text-left font-medium">{children}</th>,
        td: ({ children }) => <td className="border border-border px-2 py-1 align-top">{children}</td>,
        hr: () => <hr className="my-3 border-border" />,
        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm",
          isUser
            ? "bg-primary text-primary-foreground rounded-br-md"
            : "bg-card border rounded-bl-md"
        )}
      >
        {!isUser && (
          <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <Sparkles className="size-3.5" /> Relevantr
          </div>
        )}
        {message.loading ? (
          <div className="flex items-center gap-2 text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" /> Searching and generating…
          </div>
        ) : message.error ? (
          <div className="text-red-500">{message.error}</div>
        ) : isUser ? (
          <div className="whitespace-pre-wrap">{message.content}</div>
        ) : (
          <div className="min-w-0">
            <MarkdownContent content={message.content} />
          </div>
        )}
        {!isUser && message.sources && message.sources.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {message.sources.map((s, i) => (
              <span
                key={s.id}
                className="inline-flex items-center rounded-md bg-muted px-2 py-0.5 text-[11px] text-muted-foreground"
              >
                [{i + 1}] {s.file.replace(/\.pdf$/i, "")} · p.{s.page}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ProjectView({ projectId, chatId }: { projectId: string; chatId: string }) {
  const router = useRouter();
  const { user, ready: authReady } = useRequireAuth();
  const [leftOpen, setLeftOpen] = useState(true);
  const [leftWidth, setLeftWidth] = useState(288);
  const [rightWidth, setRightWidth] = useState(380);
  const [dragging, setDragging] = useState<"left" | "right" | null>(null);
  const dragRef = useRef<{ side: "left" | "right"; startX: number; startW: number } | null>(null);
  const [rightTab, setRightTab] = useState<"sources" | "page">("sources");

  const [config, setConfig] = useState<any>(null);
  const [info, setInfo] = useState<IndexInfo | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [llmEnabled, setLlmEnabled] = useState(true);
  const [selected, setSelected] = useState<ChatSource | null>(null);
  const [viewPage, setViewPage] = useState<number>(1);
  const [asking, setAsking] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // chat persistence
  const chatLoadedRef = useRef(false);
  const chatMetaRef = useRef<{ createdAt: number }>({ createdAt: Date.now() });

  useEffect(() => {
    chatLoadedRef.current = false;
    let cancelled = false;
    (async () => {
      const chat = await loadChat(projectId, chatId);
      if (cancelled) return;
      chatMetaRef.current.createdAt = chat.createdAt || Date.now();
      setMessages(chat.messages || []);
      chatLoadedRef.current = true;
    })();
    return () => { cancelled = true; };
  }, [projectId, chatId]);

  useEffect(() => {
    if (!chatLoadedRef.current) return;
    if (asking) return; // save after response completes (and on final state)
    const title = messages.find((m) => m.role === "user")?.content.slice(0, 60) || "New chat";
    void saveChat({ id: chatId, projectId, title, createdAt: chatMetaRef.current.createdAt, updatedAt: Date.now(), messages });
  }, [messages, projectId, chatId, asking]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const refresh = useCallback(async () => {
    try {
      const [c, d, j] = await Promise.all([
        api.config().catch(() => null),
        api.documents().catch(() => ({ pdf_dir: "", pdf_dir_available: false, documents: [] })),
        api.jobs().catch(() => ({ jobs: [] })),
      ]);
      if (c) {
        setConfig(c);
        setLlmEnabled(!!c.llm_enabled);
      }
      setDocs(d.documents || []);
      setJobs(j.jobs || []);
      try {
        setInfo(await api.indexInfo());
        setError(null);
      } catch {
        setInfo(null);
      }
    } catch (e: any) {
      setError(e?.message || "Failed to reach backend");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const activeJob = jobs.find((j) => j.status === "queued" || j.status === "running");
  useEffect(() => {
    if (!activeJob) return;
    const t = setInterval(refresh, 1500);
    return () => clearInterval(t);
  }, [activeJob, refresh]);

  // resizable sidebars
  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: PointerEvent) => {
      const d = dragRef.current;
      if (!d) return;
      if (d.side === "left") setLeftWidth(Math.min(480, Math.max(220, d.startW + (e.clientX - d.startX))));
      else setRightWidth(Math.min(560, Math.max(280, d.startW - (e.clientX - d.startX))));
    };
    const onUp = () => {
      setDragging(null);
      dragRef.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [dragging]);

  const startDrag = (side: "left" | "right", e: React.PointerEvent) => {
    e.preventDefault();
    dragRef.current = { side, startX: e.clientX, startW: side === "left" ? leftWidth : rightWidth };
    setDragging(side);
  };

  const latestAssistant = [...messages].reverse().find((m) => m.role === "assistant" && m.sources?.length);
  const latestSources = latestAssistant?.sources || [];

  useEffect(() => {
    if (!selected && latestSources.length) setSelected(latestSources[0]);
  }, [latestSources, selected]);

  const openSource = (ref: ChatSource) => {
    setSelected(ref);
    setViewPage(ref.page);
    setRightTab("page");
  };

  useEffect(() => {
    if (selected) setViewPage(selected.page);
  }, [selected?.id]);

  const runJob = async (kind: "build" | "update" | "rebuild") => {
    setBusy(kind);
    try {
      if (kind === "build") await api.build();
      else if (kind === "update") await api.update();
      else await api.rebuild();
      await refresh();
    } catch (e: any) {
      setError(e?.message || "Failed to start job");
    } finally {
      setBusy(null);
    }
  };

  const send = async () => {
    const q = input.trim();
    if (!q || asking) return;
    setInput("");
    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", content: q };
    const asstId = crypto.randomUUID();
    const asstMsg: ChatMessage = { id: asstId, role: "assistant", content: "", loading: true };
    setMessages((m) => [...m, userMsg, asstMsg]);
    setAsking(true);
    try {
      const res = await api.query({ question: q, use_llm: llmEnabled });
      const sources: ChatSource[] = (res.passages || []).map((p, i) => ({
        id: `${asstId}-${i}`,
        file: p.source,
        page: p.page,
        score: p.score,
        snippet: p.text.slice(0, 500),
      }));
      const content = res.answer || (sources.length ? "Retrieved passages (LLM off):" : "No matching passages found.");
      setMessages((m) => m.map((msg) => (msg.id === asstId ? { ...msg, loading: false, content, sources } : msg)));
      if (sources.length) {
        setSelected(sources[0]);
        setRightTab("sources");
      }
    } catch (e: any) {
      setMessages((m) => m.map((msg) => (msg.id === asstId ? { ...msg, loading: false, error: e?.message || "Query failed" } : msg)));
    } finally {
      setAsking(false);
    }
  };

  const newChat = () => router.push(`/project/${projectId}/chat/${crypto.randomUUID()}`);

  const readyCount = docs.filter((s) => s.state === "ready").length;
  const embeddingDoc = docs.find((s) => s.state === "embedding");

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      <header className="flex h-14 shrink-0 items-center justify-between border-b bg-card px-3">
        <div className="flex items-center gap-2">
          <Link href="/" className="flex size-8 items-center justify-center rounded-md hover:bg-muted" title="Back to projects">
            <ChevronLeft className="size-4" />
          </Link>
          <div className="flex size-7 items-center justify-center rounded-md border bg-background">
            <BookOpen className="size-3.5" />
          </div>
          <div className="leading-tight">
            <p className="text-sm font-semibold">Library</p>
            <p className="text-[11px] text-muted-foreground">
              {info ? `${info.documents} papers · ${info.chunks.toLocaleString()} chunks` : "No index yet"} · Qdrant
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {activeJob ? (
            <Badge variant="warning" className="hidden sm:inline-flex">
              <LoaderCircle className="mr-1 size-3 animate-spin" /> {activeJob.message || activeJob.type}
            </Badge>
          ) : info ? (
            <Badge variant="success" className="hidden sm:inline-flex">Index ready</Badge>
          ) : (
            <Badge variant="secondary" className="hidden sm:inline-flex">Not indexed</Badge>
          )}
          <label className="hidden items-center gap-2 text-sm sm:flex">
            <span className="text-muted-foreground">LLM answers</span>
            <Switch checked={llmEnabled} onCheckedChange={setLlmEnabled} />
          </label>
          <ThemeToggle />
          {user && (
            <Button variant="ghost" size="sm" title="Log out" onClick={async () => { await api.logout().catch(() => {}); router.replace("/login"); }}>
              <LogOut className="size-3.5" /> {user.username}
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => setSettingsOpen(true)}>
            <Settings2 className="size-3.5" /> Settings
          </Button>
          <Button variant="outline" size="sm" onClick={newChat}>
            <MessageSquarePlus className="size-3.5" /> New chat
          </Button>
        </div>
      </header>

      {error && (
        <div className="border-b bg-red-500/10 px-4 py-2 text-xs text-red-600 dark:text-red-400">
          Backend: {error} — ensure FastAPI is running on port 8000 and Qdrant is up.
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        {/* Left sidebar */}
        <aside className="flex shrink-0 flex-col border-r bg-card/50" style={{ width: leftOpen ? leftWidth : 48, transition: dragging ? "none" : "width 200ms ease" }}>
          <div className="flex h-11 items-center justify-between border-b px-2">
            {leftOpen && <span className="px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Sources</span>}
            <Button variant="ghost" size="icon-sm" className={cn(!leftOpen && "mx-auto")} onClick={() => setLeftOpen((v) => !v)} title={leftOpen ? "Collapse" : "Expand sources"}>
              {leftOpen ? <PanelLeftClose className="size-4" /> : <PanelLeftOpen className="size-4" />}
            </Button>
          </div>

          {leftOpen ? (
            <>
              <div className="space-y-1 p-2">
                <div className="grid grid-cols-2 gap-1">
                  <Button variant="outline" size="sm" onClick={() => runJob("update")} disabled={!!activeJob || !!busy}>
                    <RefreshCw className={cn("size-3.5", (busy === "update" || activeJob?.type === "update") && "animate-spin")} /> Update
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => runJob("build")} disabled={!!activeJob || !!busy}>
                    <Plus className="size-3.5" /> Build
                  </Button>
                </div>
                <Button variant="ghost" size="sm" className="w-full justify-start text-xs text-muted-foreground" onClick={() => runJob("rebuild")} disabled={!!activeJob || !!busy}>
                  Rebuild index
                </Button>
              </div>
              <Separator />
              <div className="flex items-center justify-between px-3 py-2 text-[11px] text-muted-foreground">
                <span>{docs.length} files</span>
                <span>{readyCount} embedded</span>
              </div>
              <div className="flex-1 overflow-y-auto px-2 pb-2">
                <div className="space-y-1">
                  {docs.map((source) => (
                    <div key={source.name} className={cn(
                      "rounded-lg border bg-background px-2.5 py-2",
                      source.state === "embedding" && "border-amber-500/30 bg-amber-500/5",
                      source.state === "failed" && "border-red-500/30 bg-red-500/5",
                      source.state === "new" && "border-sky-500/30 bg-sky-500/5"
                    )}>
                      <div className="flex items-start gap-2">
                        <div className="mt-0.5"><SourceStateIcon state={source.state} /></div>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium leading-tight" title={source.name}>{source.name}</p>
                          <p className="mt-0.5 text-[11px] text-muted-foreground">{stateLabel(source)}</p>
                          {source.state === "embedding" && <Progress value={(activeJob?.progress || 0) * 100} className="mt-1.5" />}
                        </div>
                      </div>
                    </div>
                  ))}
                  {docs.length === 0 && (
                    <div className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                      No PDFs found. Set <code className="rounded bg-muted px-1">pdf_dir</code> in config and click Build.
                      {config?.pdf_dir ? <div className="mt-1 truncate font-mono text-[10px]">{config.pdf_dir}</div> : null}
                    </div>
                  )}
                </div>
              </div>
              {activeJob && (
                <div className="border-t bg-amber-500/5 p-2 text-[11px] text-muted-foreground">
                  <div className="flex items-center gap-1.5">
                    <LoaderCircle className="size-3 animate-spin text-amber-500" />
                    <span className="truncate">{activeJob.message || "Working…"}</span>
                  </div>
                  <Progress value={(activeJob.progress || 0) * 100} className="mt-1.5" />
                </div>
              )}
            </>
          ) : (
            <div className="flex flex-1 flex-col items-center gap-2 py-3 text-muted-foreground">
              <FileText className="size-4" />
              <span className="rotate-180 text-[10px] [writing-mode:vertical-rl] tracking-wider">SOURCES</span>
            </div>
          )}
        </aside>

        {leftOpen && (
          <div onPointerDown={(e) => startDrag("left", e)} className={cn("group relative z-10 w-1 shrink-0 cursor-col-resize hover:bg-primary/20", dragging === "left" && "bg-primary/30")} title="Drag to resize">
            <div className="absolute inset-y-0 -left-1 -right-1" />
          </div>
        )}

        {/* Center chat */}
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="flex h-11 shrink-0 items-center justify-between border-b px-4 text-xs text-muted-foreground">
            <span className="truncate">Chat: <span className="font-mono">{chatId.slice(0, 8)}</span></span>
            <button onClick={newChat} className="flex items-center gap-1 hover:text-foreground"><MessageSquarePlus className="size-3.5" /> New chat</button>
          </div>
          <div className="flex-1 overflow-y-auto">
            <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4 sm:p-6">
              {messages.length === 0 && (
                <div className="flex flex-col items-center justify-center gap-3 py-16 text-center text-muted-foreground">
                  <Sparkles className="size-8 opacity-30" />
                  <p className="text-sm font-medium text-foreground">Ask a question about your papers</p>
                  <p className="max-w-sm text-xs">Each chat has its own URL. Answers include cited passages from the indexed PDFs.</p>
                </div>
              )}
              {messages.map((m) => <MessageBubble key={m.id} message={m} />)}
              <div ref={bottomRef} />
            </div>
          </div>
          <div className="border-t bg-card/40 p-3 sm:p-4">
            <div className="mx-auto w-full max-w-3xl rounded-2xl border bg-background p-2 shadow-sm">
              <Textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                placeholder={info ? "Ask a question about your papers…" : "Build the index first, then ask a question…"}
                className="min-h-[60px] resize-none border-0 shadow-none focus-visible:ring-0"
              />
              <div className="flex items-center justify-between px-1 pb-1 pt-2">
                <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  <Badge variant={llmEnabled ? "success" : "secondary"} className="h-5 px-1.5 text-[10px]">LLM {llmEnabled ? "on" : "off"}</Badge>
                  <span>Enter to send · Shift+Enter for newline</span>
                </div>
                <Button size="sm" onClick={send} disabled={asking || !input.trim()}>
                  {asking ? <LoaderCircle className="size-3.5 animate-spin" /> : <Send className="size-3.5" />} Ask
                </Button>
              </div>
            </div>
          </div>
        </main>

        <div onPointerDown={(e) => startDrag("right", e)} className={cn("group relative z-10 w-1 shrink-0 cursor-col-resize hover:bg-primary/20", dragging === "right" && "bg-primary/30")} title="Drag to resize">
          <div className="absolute inset-y-0 -left-1 -right-1" />
        </div>

        {/* Right sidebar */}
        <aside className="flex shrink-0 flex-col border-l bg-card/50" style={{ width: rightWidth, transition: dragging ? "none" : "width 200ms ease" }}>
          <Tabs value={rightTab} onValueChange={(v) => setRightTab(v as "sources" | "page")} className="flex min-h-0 flex-1">
            <div className="flex h-11 items-center justify-between border-b px-2">
              <TabsList className="h-8">
                <TabsTrigger value="sources" className="px-3 py-1 text-xs">Sources</TabsTrigger>
                <TabsTrigger value="page" className="px-3 py-1 text-xs">Page view</TabsTrigger>
              </TabsList>
              <span className="text-[11px] text-muted-foreground">{latestSources.length ? "Latest" : "—"}</span>
            </div>

            <TabsContent value="sources" className="m-0 min-h-0 flex-1 overflow-y-auto p-2">
              {latestSources.length ? (
                <>
                  <p className="px-1 pb-2 text-[11px] text-muted-foreground">{latestSources.length} passages · double-click to open page</p>
                  <div className="space-y-2">
                    {latestSources.map((ref, i) => (
                      <button key={ref.id} onDoubleClick={() => openSource(ref)} onClick={() => setSelected(ref)}
                        className={cn("w-full rounded-lg border bg-background p-3 text-left transition-colors hover:border-foreground/20 hover:shadow-sm", selected?.id === ref.id && "border-primary/30 ring-1 ring-ring/30")}>
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate text-xs font-medium text-muted-foreground">[{i + 1}] {ref.file}</p>
                            <p className="mt-0.5 text-sm font-semibold">Page {ref.page}</p>
                          </div>
                          <Badge variant="outline" className="shrink-0 tabular-nums">{(ref.score * 100).toFixed(0)}%</Badge>
                        </div>
                        <p className="mt-2 line-clamp-4 text-xs leading-relaxed text-muted-foreground">{ref.snippet}</p>
                        <p className="mt-2 text-[10px] font-medium text-muted-foreground">Double-click to view page</p>
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-muted-foreground">
                  <Search className="size-8 opacity-40" />
                  <p className="text-sm">Ask a question to see cited sources here.</p>
                </div>
              )}
            </TabsContent>

            <TabsContent value="page" className="m-0 flex min-h-0 flex-1 flex-col overflow-hidden">
              {selected ? (
                <>
                  <div className="border-b bg-background/50 p-3">
                    <p className="truncate text-sm font-medium">{selected.file}</p>
                    <p className="text-xs text-muted-foreground">
                      Cited page {selected.page} · viewing page {viewPage} · relevance {(selected.score * 100).toFixed(0)}%
                    </p>
                  </div>
                  <div className="flex-1 overflow-y-auto p-3">
                    <div className="mb-3 rounded-lg border bg-amber-500/5 p-3">
                      <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Retrieved passage</p>
                      <p className="whitespace-pre-wrap text-xs leading-relaxed text-foreground/90">{selected.snippet}</p>
                    </div>
                    <div className="rounded-lg border bg-card p-2">
                      <PdfPageViewer fileName={selected.file} pageNumber={viewPage} />
                    </div>
                  </div>
                  <div className="flex items-center justify-between border-t bg-background/50 p-2">
                    <Button variant="outline" size="sm" onClick={() => setViewPage((p) => Math.max(1, p - 1))} disabled={viewPage <= 1}>
                      <ChevronLeft className="size-3.5" /> Prev
                    </Button>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-muted-foreground">Page {viewPage}</span>
                      {viewPage !== selected.page && (
                        <Button variant="ghost" size="xs" onClick={() => setViewPage(selected.page)}>Go to cited</Button>
                      )}
                    </div>
                    <Button variant="outline" size="sm" onClick={() => setViewPage((p) => p + 1)}>
                      Next <ChevronRight className="size-3.5" />
                    </Button>
                  </div>
                </>
              ) : (
                <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center text-muted-foreground">
                  <Search className="size-8 opacity-40" />
                  <p className="text-sm font-medium">No source selected</p>
                  <p className="text-xs">Double-click a source to view its PDF page.</p>
                </div>
              )}
            </TabsContent>
          </Tabs>
        </aside>
      </div>

      <SettingsDialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onSaved={() => { refresh(); }}
      />
    </div>
  );
}
