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

export type Project = {
  id: string;
  name: string;
  pdf_dir: string;
  qdrant_collection: string;
  created_at: number;
};

export type QueryOut = {
  question: string;
  answer: string | null;
  passages: Passage[];
  mode: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = init?.body instanceof FormData;
  const res = await fetch(path, {
    ...init,
    headers: isForm ? { ...(init?.headers || {}) } : {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      detail = j.detail || j.message || JSON.stringify(j);
    } catch {}
    const err = new Error(detail) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export const api = {
  health: () => request<{ status: string; qdrant: string; version: string }>("/api/health"),
  config: () => request<any>("/api/config"),
  putConfig: (body: any) => request<any>("/api/config", { method: "PUT", body: JSON.stringify(body) }),
  indexInfo: (projectId?: string) =>
    request<IndexInfo>(`/api/index/info${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""}`),
  documents: (projectId?: string) =>
    request<{ pdf_dir: string; pdf_dir_available: boolean; documents: Doc[] }>(`/api/index/documents${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""}`),
  build: (projectId?: string) =>
    request<Job>("/api/index/build", { method: "POST", body: JSON.stringify(projectId ? { project_id: projectId } : {}) }),
  update: (projectId?: string) =>
    request<Job>("/api/index/update", { method: "POST", body: JSON.stringify(projectId ? { project_id: projectId } : {}) }),
  rebuild: (projectId?: string) =>
    request<Job>("/api/index/rebuild", { method: "POST", body: JSON.stringify(projectId ? { project_id: projectId } : {}) }),
  jobs: () => request<{ jobs: Job[] }>("/api/jobs"),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  query: (body: { question: string; use_llm?: boolean; retrieve_k?: number; final_n?: number; project_id?: string }) =>
    request<QueryOut>("/api/query", { method: "POST", body: JSON.stringify(body) }),
  exportMd: async (question: string, projectId?: string) => {
    const params = new URLSearchParams({ question });
    if (projectId) params.set("project_id", projectId);
    const res = await fetch(`/api/export.md?${params}`);
    if (!res.ok) throw new Error("Export failed");
    return res.text();
  },
  projects: () => request<{ projects: Project[] }>("/api/projects"),
  createProject: (name: string) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name }) }),
  deleteProject: (projectId: string) =>
    request<{ ok: boolean }>(`/api/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" }),
  uploadFiles: (projectId: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return request<{ documents: Doc[] }>(`/api/projects/${encodeURIComponent(projectId)}/upload`, { method: "POST", body: fd });
  },
  llmTest: (body?: { provider?: string; base_url?: string; model?: string; key?: string }) =>
    request<{ ok: boolean; message: string }>("/api/llm/test", { method: "POST", body: JSON.stringify(body ?? {}) }),
  llmModels: (body?: { provider?: string; base_url?: string; model?: string; key?: string }) =>
    request<{ models: string[] }>("/api/llm/models", { method: "POST", body: JSON.stringify(body ?? {}) }),
  keyStatus: (provider: string) => request<{ provider: string; set: boolean; source: string }>(`/api/keys/${provider}`),
  setKey: (provider: string, key: string) => request<{ provider: string; set: boolean; source: string }>(`/api/keys/${provider}`, { method: "PUT", body: JSON.stringify({ key }) }),
  deleteKey: (provider: string) => request<{ provider: string; set: boolean; source: string }>(`/api/keys/${provider}`, { method: "DELETE" }),
  listChats: (projectId: string) => request<{ chats: any[] }>(`/api/projects/${encodeURIComponent(projectId)}/chats`),
  getChat: (chatId: string) => request<any>(`/api/chats/${encodeURIComponent(chatId)}`),
  saveChat: (chatId: string, body: { project_id: string; title?: string; messages: any[] }) =>
    request<any>(`/api/chats/${encodeURIComponent(chatId)}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteChat: (chatId: string) => request<{ ok: boolean }>(`/api/chats/${encodeURIComponent(chatId)}`, { method: "DELETE" }),
  register: (username: string, password: string) =>
    request<{ user: { id: string; username: string } }>("/api/auth/register", { method: "POST", body: JSON.stringify({ username, password }) }),
  login: (username: string, password: string) =>
    request<{ user: { id: string; username: string } }>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  me: () => request<{ user: { id: string; username: string } }>("/api/auth/me"),
};
