export type Job = {
  id: string;
  type: string;
  status: string;
  progress: number;
  message?: string | null;
  error?: string | null;
  result?: any;
  created_at: number;
  started_at?: number | null;
  finished_at?: number | null;
};

export type IndexInfo = {
  db_dir: string;
  pdf_dir: string;
  pdf_dir_available: boolean;
  embedding_model: string;
  embedding_dim: number;
  chunk_size: number;
  chunk_overlap: number;
  documents: number;
  chunks: number;
  created_at: string;
  updated_at: string;
};

export type Doc = {
  name: string;
  state: "ready" | "new" | "embedding" | "failed";
  chunks?: number | null;
  pages?: number | null;
  size?: number | null;
};

export type Passage = {
  text: string;
  source: string;
  page: number;
  score: number;
};

export type QueryOut = {
  question: string;
  answer: string | null;
  passages: Passage[];
  mode: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      detail = j.detail || j.message || JSON.stringify(j);
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  health: () => request<{ status: string; qdrant: string; version: string }>("/api/health"),
  config: () => request<any>("/api/config"),
  putConfig: (body: any) => request<any>("/api/config", { method: "PUT", body: JSON.stringify(body) }),
  indexInfo: () => request<IndexInfo>("/api/index/info"),
  documents: () => request<{ pdf_dir: string; pdf_dir_available: boolean; documents: Doc[] }>("/api/index/documents"),
  build: (pdf_dir?: string) => request<Job>("/api/index/build", { method: "POST", body: JSON.stringify(pdf_dir ? { pdf_dir } : {}) }),
  update: (pdf_dir?: string) => request<Job>("/api/index/update", { method: "POST", body: JSON.stringify(pdf_dir ? { pdf_dir } : {}) }),
  rebuild: (pdf_dir?: string) => request<Job>("/api/index/rebuild", { method: "POST", body: JSON.stringify(pdf_dir ? { pdf_dir } : {}) }),
  jobs: () => request<{ jobs: Job[] }>("/api/jobs"),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  query: (body: { question: string; use_llm?: boolean; retrieve_k?: number; final_n?: number }) =>
    request<QueryOut>("/api/query", { method: "POST", body: JSON.stringify(body) }),
  exportMd: async (question: string) => {
    const res = await fetch(`/api/export.md?question=${encodeURIComponent(question)}`);
    if (!res.ok) throw new Error("Export failed");
    return res.text();
  },
  llmTest: () => request<{ ok: boolean; message: string }>("/api/llm/test", { method: "POST" }),
  llmModels: () => request<{ models: string[] }>("/api/llm/models"),
  keyStatus: (provider: string) => request<{ provider: string; set: boolean; source: string }>(`/api/keys/${provider}`),
  setKey: (provider: string, key: string) => request<{ provider: string; set: boolean; source: string }>(`/api/keys/${provider}`, { method: "PUT", body: JSON.stringify({ key }) }),
  deleteKey: (provider: string) => request<{ provider: string; set: boolean; source: string }>(`/api/keys/${provider}`, { method: "DELETE" }),
};
