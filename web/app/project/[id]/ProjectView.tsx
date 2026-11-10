"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  FileText,
  LoaderCircle,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Search,
  Send,
  Settings2,
  Sparkles,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/utils";
import {
  demoMessages,
  demoSources,
  projects,
  type ChatMessage,
  type SourceFile,
  type SourceRef,
} from "@/lib/demo-data";

function SourceStateIcon({ state }: { state: SourceFile["state"] }) {
  if (state === "ready") return <CircleCheck className="size-4 text-emerald-500" />;
  if (state === "embedding") return <LoaderCircle className="size-4 animate-spin text-amber-500" />;
  if (state === "new") return <CircleDashed className="size-4 text-sky-500" />;
  return <CircleAlert className="size-4 text-red-500" />;
}

function stateLabel(source: SourceFile) {
  if (source.state === "ready") return `${source.chunks ?? 0} chunks`;
  if (source.state === "embedding") return `Embedding ${source.progress ?? 0}%`;
  if (source.state === "new") return "New, not embedded";
  return "Failed";
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
        <div className="whitespace-pre-wrap">{message.content}</div>
        {!isUser && message.sources && (
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

export default function ProjectView({ id }: { id: string }) {
  const project = useMemo(
    () =>
      projects.find((p) => p.id === id) ?? {
        ...projects[0],
        id,
        name: id === "new" ? "New project" : projects[0].name,
        description:
          id === "new"
            ? "Add sources and start asking questions."
            : projects[0].description,
        papers: id === "new" ? 0 : projects[0].papers,
        chunks: id === "new" ? 0 : projects[0].chunks,
      },
    [id]
  );
  const [leftOpen, setLeftOpen] = useState(true);
  const [leftWidth, setLeftWidth] = useState(288);
  const [rightWidth, setRightWidth] = useState(380);
  const [dragging, setDragging] = useState<"left" | "right" | null>(null);
  const dragRef = useRef<{ side: "left" | "right"; startX: number; startW: number } | null>(null);
  const [rightTab, setRightTab] = useState<"sources" | "page">("sources");
  const [selected, setSelected] = useState<SourceRef | null>(demoMessages[1].sources?.[0] ?? null);
  const [input, setInput] = useState("");
  const [llmEnabled, setLlmEnabled] = useState(true);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: PointerEvent) => {
      const d = dragRef.current;
      if (!d) return;
      if (d.side === "left") {
        const next = Math.min(480, Math.max(220, d.startW + (e.clientX - d.startX)));
        setLeftWidth(next);
      } else {
        const next = Math.min(560, Math.max(280, d.startW - (e.clientX - d.startX)));
        setRightWidth(next);
      }
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
    const startW = side === "left" ? leftWidth : rightWidth;
    dragRef.current = { side, startX: e.clientX, startW };
    setDragging(side);
  };

  const latestAnswer = demoMessages[demoMessages.length - 1];
  const latestSources = latestAnswer.sources ?? [];
  const readyCount = demoSources.filter((s) => s.state === "ready").length;
  const embedding = demoSources.find((s) => s.state === "embedding");

  const openSource = (ref: SourceRef) => {
    setSelected(ref);
    setRightTab("page");
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      {/* Header */}
      <header className="flex h-14 shrink-0 items-center justify-between border-b bg-card px-3">
        <div className="flex items-center gap-2">
          <Link
            href="/"
            className="flex size-8 items-center justify-center rounded-md hover:bg-muted"
            title="Back to projects"
          >
            <ChevronLeft className="size-4" />
          </Link>
          <div className="flex size-7 items-center justify-center rounded-md border bg-background">
            <BookOpen className="size-3.5" />
          </div>
          <div className="leading-tight">
            <p className="text-sm font-semibold">{project.name}</p>
            <p className="text-[11px] text-muted-foreground">
              {project.papers} papers · {project.chunks.toLocaleString()} chunks · Qdrant
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant="success" className="hidden sm:inline-flex">
            Index ready
          </Badge>
          <label className="hidden items-center gap-2 text-sm sm:flex">
            <span className="text-muted-foreground">LLM answers</span>
            <Switch checked={llmEnabled} onCheckedChange={setLlmEnabled} />
          </label>
          <ThemeToggle />
          <Button variant="outline" size="sm">
            <Settings2 className="size-3.5" /> Settings
          </Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Left sidebar */}
        <aside
          className="flex shrink-0 flex-col border-r bg-card/50"
          style={{ width: leftOpen ? leftWidth : 48, transition: dragging ? "none" : "width 200ms ease" }}
        >
          <div className="flex h-11 items-center justify-between border-b px-2">
            {leftOpen && <span className="px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Sources</span>}
            <Button
              variant="ghost"
              size="icon-sm"
              className={cn(!leftOpen && "mx-auto")}
              onClick={() => setLeftOpen((v) => !v)}
              title={leftOpen ? "Collapse" : "Expand sources"}
            >
              {leftOpen ? <PanelLeftClose className="size-4" /> : <PanelLeftOpen className="size-4" />}
            </Button>
          </div>

          {leftOpen ? (
            <>
              <div className="p-2">
                <Button variant="outline" className="w-full justify-start">
                  <Plus className="size-4" /> Add source
                </Button>
              </div>
              <Separator />
              <div className="flex items-center justify-between px-3 py-2 text-[11px] text-muted-foreground">
                <span>{demoSources.length} files</span>
                <span>{readyCount} embedded</span>
              </div>
              <div className="flex-1 overflow-y-auto px-2 pb-2">
                <div className="space-y-1">
                  {demoSources.map((source) => (
                    <div
                      key={source.id}
                      className={cn(
                        "rounded-lg border bg-background px-2.5 py-2",
                        source.state === "embedding" && "border-amber-500/30 bg-amber-500/5",
                        source.state === "failed" && "border-red-500/30 bg-red-500/5",
                        source.state === "new" && "border-sky-500/30 bg-sky-500/5"
                      )}
                    >
                      <div className="flex items-start gap-2">
                        <div className="mt-0.5"><SourceStateIcon state={source.state} /></div>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium leading-tight" title={source.name}>
                            {source.name}
                          </p>
                          <p className="mt-0.5 text-[11px] text-muted-foreground">
                            {source.pages} pages · {stateLabel(source)}
                          </p>
                          {source.state === "embedding" && (
                            <Progress value={source.progress} className="mt-1.5" />
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              {embedding && (
                <div className="border-t bg-amber-500/5 p-2 text-[11px] text-muted-foreground">
                  <div className="flex items-center gap-1.5">
                    <LoaderCircle className="size-3 animate-spin text-amber-500" />
                    Embedding in progress…
                  </div>
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
          <div
            onPointerDown={(e) => startDrag("left", e)}
            className={cn(
              "group relative z-10 w-1 shrink-0 cursor-col-resize bg-transparent hover:bg-primary/20 active:bg-primary/30",
              dragging === "left" && "bg-primary/30"
            )}
            title="Drag to resize"
          >
            <div className="absolute inset-y-0 -left-1 -right-1" />
          </div>
        )}

        {/* Center chat */}
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="flex-1 overflow-y-auto">
            <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4 sm:p-6">
              {demoMessages.map((m) => (
                <MessageBubble key={m.id} message={m} />
              ))}
            </div>
          </div>
          <div className="border-t bg-card/40 p-3 sm:p-4">
            <div className="mx-auto w-full max-w-3xl rounded-2xl border bg-background p-2 shadow-sm">
              <Textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask a question about your papers…"
                className="min-h-[60px] resize-none border-0 shadow-none focus-visible:ring-0"
              />
              <div className="flex items-center justify-between px-1 pb-1 pt-2">
                <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  <Badge variant={llmEnabled ? "success" : "secondary"} className="h-5 px-1.5 text-[10px]">
                    LLM {llmEnabled ? "on" : "off"}
                  </Badge>
                  <span>Answers cite file &amp; page</span>
                </div>
                <Button size="sm" disabled>
                  <Send className="size-3.5" /> Ask
                </Button>
              </div>
            </div>
            <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-muted-foreground">
              Demo UI — actions are not connected to the backend yet.
            </p>
          </div>
        </main>

        <div
          onPointerDown={(e) => startDrag("right", e)}
          className={cn(
            "group relative z-10 w-1 shrink-0 cursor-col-resize bg-transparent hover:bg-primary/20 active:bg-primary/30",
            dragging === "right" && "bg-primary/30"
          )}
          title="Drag to resize"
        >
          <div className="absolute inset-y-0 -left-1 -right-1" />
        </div>

        {/* Right sidebar */}
        <aside
          className="flex shrink-0 flex-col border-l bg-card/50"
          style={{ width: rightWidth, transition: dragging ? "none" : "width 200ms ease" }}
        >
          <Tabs
            value={rightTab}
            onValueChange={(v) => setRightTab(v as "sources" | "page")}
            className="flex min-h-0 flex-1"
          >
            <div className="flex h-11 items-center justify-between border-b px-2">
              <TabsList className="h-8">
                <TabsTrigger value="sources" className="px-3 py-1 text-xs">Sources</TabsTrigger>
                <TabsTrigger value="page" className="px-3 py-1 text-xs">Page view</TabsTrigger>
              </TabsList>
              <span className="text-[11px] text-muted-foreground">Latest response</span>
            </div>

            <TabsContent value="sources" className="m-0 min-h-0 flex-1 overflow-y-auto p-2">
              <p className="px-1 pb-2 text-[11px] text-muted-foreground">
                {latestSources.length} passages from the latest response · double-click to open page
              </p>
              <div className="space-y-2">
                {latestSources.map((ref, i) => (
                  <button
                    key={ref.id}
                    onDoubleClick={() => openSource(ref)}
                    onClick={() => setSelected(ref)}
                    className={cn(
                      "w-full rounded-lg border bg-background p-3 text-left transition-colors hover:border-foreground/20 hover:shadow-sm",
                      selected?.id === ref.id && "border-primary/30 ring-1 ring-ring/30"
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-xs font-medium text-muted-foreground">[{i + 1}] {ref.file}</p>
                        <p className="mt-0.5 text-sm font-semibold">Page {ref.page}</p>
                      </div>
                      <Badge variant="outline" className="shrink-0 tabular-nums">{(ref.score * 100).toFixed(0)}%</Badge>
                    </div>
                    <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-muted-foreground">{ref.snippet}</p>
                    <p className="mt-2 text-[10px] font-medium text-muted-foreground">Double-click to view page</p>
                  </button>
                ))}
              </div>
            </TabsContent>

            <TabsContent value="page" className="m-0 flex min-h-0 flex-1 flex-col overflow-hidden">
              {selected ? (
                <>
                  <div className="border-b bg-background/50 p-3">
                    <p className="truncate text-sm font-medium">{selected.file}</p>
                    <p className="text-xs text-muted-foreground">Page {selected.page} · relevance {(selected.score * 100).toFixed(0)}%</p>
                  </div>
                  <div className="flex-1 overflow-y-auto p-3">
                    <div className="rounded-lg border bg-white p-5 shadow-sm dark:bg-neutral-950">
                      <div className="mb-4 flex items-center justify-between border-b pb-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                        <span className="truncate pr-4">{selected.file}</span>
                        <span>Page {selected.page}</span>
                      </div>
                      <div className="space-y-3 text-[13px] leading-7 text-foreground/90">
                        <p className="text-sm font-semibold tracking-tight">4.2 Hydrogen pickup and hydride formation</p>
                        <p>{selected.snippet}</p>
                        <p className="text-muted-foreground">
                          Further analysis shows that hydride orientation relative to the applied stress
                          field governs crack propagation susceptibility, particularly near the metal–oxide
                          interface where local hydrogen concentration is elevated.
                        </p>
                        <p className="rounded-md bg-amber-200/50 px-2 py-1 dark:bg-amber-500/15">
                          Highlighted region corresponds to the retrieved passage.
                        </p>
                      </div>
                    </div>
                    <div className="mt-3 rounded-lg border border-dashed bg-muted/30 p-3 text-xs text-muted-foreground">
                      <p className="font-medium text-foreground">PDF viewer (planned)</p>
                      <p className="mt-1 leading-relaxed">
                        This panel will render the actual PDF page via <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">react-pdf</code> from the
                        source file, scrolled/highlighted to page {selected.page}.
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center justify-between border-t bg-background/50 p-2">
                    <Button variant="outline" size="sm"><ChevronLeft className="size-3.5" /> Prev</Button>
                    <span className="text-xs font-medium text-muted-foreground">Page {selected.page}</span>
                    <Button variant="outline" size="sm">Next <ChevronRight className="size-3.5" /></Button>
                  </div>
                </>
              ) : (
                <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center text-muted-foreground">
                  <Search className="size-8 opacity-40" />
                  <p className="text-sm font-medium">No source selected</p>
                  <p className="text-xs">Double-click a source to view its page here.</p>
                </div>
              )}
            </TabsContent>
          </Tabs>
        </aside>
      </div>
    </div>
  );
}
