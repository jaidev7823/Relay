import { api } from "./api";

export type ChatSource = {
  id: string;
  file: string;
  page: number;
  score: number;
  snippet: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: ChatSource[];
  loading?: boolean;
  error?: string;
  created_at?: number;
};

export type ChatThread = {
  id: string;
  projectId: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ChatMessage[];
};

const key = (projectId: string, chatId: string) => `relevantr:chat:${projectId}:${chatId}`;

function emptyChat(projectId: string, chatId: string): ChatThread {
  return { id: chatId, projectId, title: "New chat", createdAt: Date.now(), updatedAt: Date.now(), messages: [] };
}

function fromApi(data: any, projectId: string, chatId: string): ChatThread {
  return {
    id: data.id || chatId,
    projectId: data.project_id || projectId,
    title: data.title || "New chat",
    createdAt: (data.created_at || Date.now() / 1000) * (data.created_at > 1e12 ? 1 : 1000),
    updatedAt: (data.updated_at || Date.now() / 1000) * (data.updated_at > 1e12 ? 1 : 1000),
    messages: (data.messages || []).map((m: any) => ({
      id: m.id,
      role: m.role,
      content: m.content || "",
      sources: m.sources || undefined,
      error: m.error || undefined,
      created_at: m.created_at,
    })),
  };
}

export async function loadChat(projectId: string, chatId: string): Promise<ChatThread> {
  try {
    const data = await api.getChat(chatId);
    const chat = fromApi(data, projectId, chatId);
    cacheChat(chat);
    return chat;
  } catch {
    // fallback to local cache
  }
  if (typeof window !== "undefined") {
    try {
      const raw = localStorage.getItem(key(projectId, chatId));
      if (raw) return JSON.parse(raw);
    } catch {}
  }
  return emptyChat(projectId, chatId);
}

export function cacheChat(chat: ChatThread) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(key(chat.projectId, chat.id), JSON.stringify(chat));
  } catch {}
}

export async function saveChat(chat: ChatThread): Promise<void> {
  cacheChat(chat);
  try {
    await api.saveChat(chat.id, {
      project_id: chat.projectId,
      title: chat.title,
      messages: chat.messages
        .filter((m) => !m.loading)
        .map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          sources: m.sources,
          error: m.error,
          created_at: m.created_at,
        })),
    });
  } catch {
    // keep local cache; backend may be offline
  }
}

export async function listChats(projectId: string): Promise<ChatThread[]> {
  try {
    const data = await api.listChats(projectId);
    return (data.chats || []).map((c: any) => fromApi(c, projectId, c.id));
  } catch {
    return [];
  }
}
