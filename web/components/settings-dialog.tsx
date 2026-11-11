"use client";

import { useEffect, useState } from "react";
import { Check, KeyRound, LoaderCircle, PlugZap, Save, Server, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const PROVIDERS = [
  { id: "gwdg", label: "GWDG Chat AI" },
  { id: "openai", label: "OpenAI" },
  { id: "gemini", label: "Gemini" },
  { id: "ollama", label: "Ollama" },
  { id: "custom", label: "Custom" },
];

export function SettingsDialog({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const [cfg, setCfg] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const [llmTesting, setLlmTesting] = useState(false);
  const [llmResult, setLlmResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);

  const [keyStatuses, setKeyStatuses] = useState<Record<string, { set: boolean; source: string }>>({});
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({});
  const [keyBusy, setKeyBusy] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setErr(null);
    setMsg(null);
    (async () => {
      try {
        const c = await api.config();
        setCfg(c);
        const statuses: Record<string, { set: boolean; source: string }> = {};
        await Promise.all(
          PROVIDERS.map(async (p) => {
            try {
              const s = await api.keyStatus(p.id);
              statuses[p.id] = { set: s.set, source: s.source };
            } catch {
              statuses[p.id] = { set: false, source: "unknown" };
            }
          })
        );
        setKeyStatuses(statuses);
      } catch (e: any) {
        setErr(e?.message || "Failed to load settings");
      } finally {
        setLoading(false);
      }
    })();
  }, [open]);

  if (!open) return null;

  const set = (key: string, value: any) => setCfg((c: any) => ({ ...c, [key]: value }));

  const save = async () => {
    if (!cfg) return;
    setSaving(true);
    setErr(null);
    setMsg(null);
    try {
      const body = {
        pdf_dir: cfg.pdf_dir,
        chunk_size: Number(cfg.chunk_size),
        chunk_overlap: Number(cfg.chunk_overlap),
        retrieve_k: Number(cfg.retrieve_k),
        final_n: Number(cfg.final_n),
        use_reranker: !!cfg.use_reranker,
        llm_enabled: !!cfg.llm_enabled,
        llm_provider: cfg.llm_provider,
        llm_base_url: cfg.llm_base_url,
        llm_model: cfg.llm_model,
      };
      const saved = await api.putConfig(body);
      setCfg(saved);
      setMsg("Settings saved.");
      onSaved?.();
    } catch (e: any) {
      setErr(e?.message || "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  const testLlm = async () => {
    setLlmTesting(true);
    setLlmResult(null);
    try {
      const res = await api.llmTest();
      setLlmResult(res);
    } catch (e: any) {
      setLlmResult({ ok: false, message: e?.message || "Test failed" });
    } finally {
      setLlmTesting(false);
    }
  };

  const loadModels = async () => {
    setModelsLoading(true);
    try {
      const res = await api.llmModels();
      setModels(res.models || []);
    } catch (e: any) {
      setErr(e?.message || "Failed to list models");
    } finally {
      setModelsLoading(false);
    }
  };

  const saveKey = async (provider: string) => {
    const val = keyInputs[provider]?.trim();
    if (!val) return;
    setKeyBusy(provider);
    try {
      const s = await api.setKey(provider, val);
      setKeyStatuses((k) => ({ ...k, [provider]: { set: s.set, source: s.source } }));
      setKeyInputs((k) => ({ ...k, [provider]: "" }));
      setMsg(`${provider} key saved.`);
    } catch (e: any) {
      setErr(e?.message || "Failed to save key");
    } finally {
      setKeyBusy(null);
    }
  };

  const removeKey = async (provider: string) => {
    setKeyBusy(provider);
    try {
      await api.deleteKey(provider);
      setKeyStatuses((k) => ({ ...k, [provider]: { set: false, source: "removed" } }));
      setMsg(`${provider} key removed.`);
    } catch (e: any) {
      setErr(e?.message || "Failed to remove key");
    } finally {
      setKeyBusy(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border bg-background shadow-xl">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div>
            <h2 className="text-base font-semibold">Settings</h2>
            <p className="text-xs text-muted-foreground">Configure indexing, retrieval, and LLM providers.</p>
          </div>
          <Button variant="ghost" size="icon-sm" onClick={onClose}><X className="size-4" /></Button>
        </div>

        {loading || !cfg ? (
          <div className="flex flex-1 items-center justify-center p-10 text-muted-foreground">
            <LoaderCircle className="mr-2 size-4 animate-spin" /> Loading settings…
          </div>
        ) : (
          <Tabs defaultValue="index" className="flex min-h-0 flex-1 flex-col">
            <div className="border-b px-4 pt-2">
              <TabsList>
                <TabsTrigger value="index"><Server className="mr-1.5 size-3.5" />Index & Retrieval</TabsTrigger>
                <TabsTrigger value="llm"><PlugZap className="mr-1.5 size-3.5" />LLM</TabsTrigger>
              </TabsList>
            </div>

            <div className="flex-1 overflow-y-auto p-4">
              <TabsContent value="index" className="m-0 space-y-4">
                <Field label="PDF folder (server path)" hint="Folder scanned for PDFs to index.">
                  <Input value={cfg.pdf_dir || ""} onChange={(e) => set("pdf_dir", e.target.value)} placeholder="/path/to/papers" />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Chunk size" hint="Tokens per chunk."><Input type="number" value={cfg.chunk_size} onChange={(e) => set("chunk_size", e.target.value)} /></Field>
                  <Field label="Chunk overlap"><Input type="number" value={cfg.chunk_overlap} onChange={(e) => set("chunk_overlap", e.target.value)} /></Field>
                  <Field label="Retrieve k" hint="Candidates before rerank."><Input type="number" value={cfg.retrieve_k} onChange={(e) => set("retrieve_k", e.target.value)} /></Field>
                  <Field label="Final n" hint="Passages sent to LLM."><Input type="number" value={cfg.final_n} onChange={(e) => set("final_n", e.target.value)} /></Field>
                </div>
                <div className="flex items-center justify-between rounded-lg border p-3">
                  <div>
                    <p className="text-sm font-medium">Use reranker</p>
                    <p className="text-xs text-muted-foreground">Cross-encoder reranking for better passage ordering.</p>
                  </div>
                  <Switch checked={!!cfg.use_reranker} onCheckedChange={(v) => set("use_reranker", v)} />
                </div>
                <div className="rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
                  <p><span className="font-medium text-foreground">Backend:</span> {cfg.vector_backend} · {cfg.embedding_backend}</p>
                  <p className="mt-1 truncate"><span className="font-medium text-foreground">Qdrant:</span> {cfg.qdrant_url} / {cfg.qdrant_collection}</p>
                </div>
              </TabsContent>

              <TabsContent value="llm" className="m-0 space-y-4">
                <div className="flex items-center justify-between rounded-lg border p-3">
                  <div>
                    <p className="text-sm font-medium">Enable LLM answers</p>
                    <p className="text-xs text-muted-foreground">When off, queries return retrieved passages only.</p>
                  </div>
                  <Switch checked={!!cfg.llm_enabled} onCheckedChange={(v) => set("llm_enabled", v)} />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <Field label="Provider">
                    <select
                      className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                      value={cfg.llm_provider || "gwdg"}
                      onChange={(e) => set("llm_provider", e.target.value)}
                    >
                      {PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                    </select>
                  </Field>
                  <Field label="Model">
                    <Input value={cfg.llm_model || ""} onChange={(e) => set("llm_model", e.target.value)} placeholder="model name" />
                  </Field>
                </div>

                {(() => {
                  const provider = cfg.llm_provider || "gwdg";
                  const providerLabel = PROVIDERS.find((p) => p.id === provider)?.label || provider;
                  const st = keyStatuses[provider];
                  const needsKey = provider !== "ollama";
                  return (
                    <div className="rounded-lg border p-3">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <KeyRound className="size-4 text-muted-foreground" />
                          <span className="text-sm font-medium">{providerLabel} API key</span>
                          {st?.set ? <Badge variant="success">Set</Badge> : <Badge variant={needsKey ? "secondary" : "outline"}>{needsKey ? "Not set" : "Optional"}</Badge>}
                        </div>
                        {st?.set && <span className="max-w-[50%] truncate text-[11px] text-muted-foreground">{st.source}</span>}
                      </div>
                      <p className="mb-2 text-xs text-muted-foreground">
                        {needsKey
                          ? `Used when "${providerLabel}" is selected. Stored server-side (keyring/env), never shown in the browser.`
                          : "Ollama usually runs locally and may not require an API key."}
                      </p>
                      <div className="flex gap-2">
                        <Input
                          type="password"
                          value={keyInputs[provider] || ""}
                          onChange={(e) => setKeyInputs((k) => ({ ...k, [provider]: e.target.value }))}
                          placeholder={st?.set ? "Enter new key to replace…" : "Enter API key…"}
                        />
                        <Button size="sm" onClick={() => saveKey(provider)} disabled={keyBusy === provider || !keyInputs[provider]?.trim()}>
                          <Save className="size-3.5" /> Save
                        </Button>
                        {st?.set && (
                          <Button variant="outline" size="sm" onClick={() => removeKey(provider)} disabled={keyBusy === provider} title="Remove key">
                            <Trash2 className="size-3.5" />
                          </Button>
                        )}
                      </div>
                    </div>
                  );
                })()}

                <Field label="Base URL" hint="OpenAI-compatible endpoint.">
                  <Input value={cfg.llm_base_url || ""} onChange={(e) => set("llm_base_url", e.target.value)} placeholder="https://..." />
                </Field>
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="outline" size="sm" onClick={testLlm} disabled={llmTesting}>
                    {llmTesting ? <LoaderCircle className="size-3.5 animate-spin" /> : <PlugZap className="size-3.5" />} Test connection
                  </Button>
                  <Button variant="outline" size="sm" onClick={loadModels} disabled={modelsLoading}>
                    {modelsLoading ? <LoaderCircle className="size-3.5 animate-spin" /> : <Server className="size-3.5" />} Load models
                  </Button>
                </div>
                {llmResult && (
                  <div className={cnBox(llmResult.ok)}>
                    {llmResult.ok ? <Check className="mr-1.5 size-3.5" /> : <X className="mr-1.5 size-3.5" />}
                    {llmResult.message}
                  </div>
                )}
                {models.length > 0 && (
                  <div className="rounded-lg border p-3">
                    <p className="mb-2 text-xs font-medium text-muted-foreground">Available models (click to select)</p>
                    <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">
                      {models.map((m) => (
                        <button key={m} onClick={() => set("llm_model", m)}
                          className={`rounded-md border px-2 py-1 text-xs hover:bg-muted ${cfg.llm_model === m ? "border-primary bg-primary/5" : ""}`}>
                          {m}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </TabsContent>

             
            </div>
          </Tabs>
        )}

        <div className="flex items-center justify-between border-t px-4 py-3">
          <div className="text-xs">
            {err && <span className="text-red-500">{err}</span>}
            {msg && !err && <span className="text-emerald-600 dark:text-emerald-400">{msg}</span>}
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose}>Close</Button>
            <Button onClick={save} disabled={saving || loading || !cfg}>
              {saving ? <LoaderCircle className="size-3.5 animate-spin" /> : <Save className="size-3.5" />} Save settings
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <label className="text-sm font-medium">{label}</label>
        {hint && <span className="text-[11px] text-muted-foreground">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function cnBox(ok: boolean) {
  return `flex items-center rounded-md border p-2 text-xs ${ok ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400" : "border-red-500/30 bg-red-500/5 text-red-600 dark:text-red-400"}`;
}
