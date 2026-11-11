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
  /** true when the backend said this chat does not exist for this user
   *  (owned by another account or deleted). UI shows a notice instead of a
   *  misleading empty chat. */
  notFound?: boolean;
};

// Local cache is keyed per user so two accounts in the same browser
// never see each other's cached chats.
let currentUserId = "anon";

export function setCurrentUserId(userId: string) {
  currentUserId = userId || "anon";
  purgeLegacyCache();
}

const key = (projectId: string, chatId: string) =>
  `relevantr:chat:${currentUserId}:${projectId}:${chatId}`;

/** Remove pre-auth cache entries (relevantr:chat:<projectId>:<chatId>)
 *  which were shared across accounts on the same browser. */
function purgeLegacyCache() {
  if (typeof window === "undefined") return;
  try {
    const dead: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k?.startsWith("relevantr:chat:")) {
        const parts = k.split(":");
        // legacy = 4 parts (no user id), current = 5 parts
        if (parts.length === 4) dead.push(k);
      }
    }
    dead.forEach((k) => localStorage.removeItem(k));
  } catch {}
}

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
  } catch (e: any) {
    // 401/404: the backend has decided this chat is not ours. Do NOT fall
    // back to the local cache — that could leak another account's chat.
    if (e?.status === 401 || e?.status === 404) {
      return { ...emptyChat(projectId, chatId), notFound: true };
    }
    // Other errors (backend offline): fall back to the local cache.
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
