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
const listKey = (projectId: string) => `relevantr:chats:${projectId}`;

export function loadChat(projectId: string, chatId: string): ChatThread {
  if (typeof window === "undefined") {
    return { id: chatId, projectId, title: "New chat", createdAt: Date.now(), updatedAt: Date.now(), messages: [] };
  }
  try {
    const raw = localStorage.getItem(key(projectId, chatId));
    if (raw) return JSON.parse(raw);
  } catch {}
  return { id: chatId, projectId, title: "New chat", createdAt: Date.now(), updatedAt: Date.now(), messages: [] };
}

export function saveChat(chat: ChatThread) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(key(chat.projectId, chat.id), JSON.stringify(chat));
    const raw = localStorage.getItem(listKey(chat.projectId));
    const ids: string[] = raw ? JSON.parse(raw) : [];
    if (!ids.includes(chat.id)) {
      ids.unshift(chat.id);
      localStorage.setItem(listKey(chat.projectId), JSON.stringify(ids.slice(0, 50)));
    }
  } catch {}
}

export function listChats(projectId: string): ChatThread[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(listKey(projectId));
    const ids: string[] = raw ? JSON.parse(raw) : [];
    return ids.map((id) => loadChat(projectId, id)).sort((a, b) => b.updatedAt - a.updatedAt);
  } catch {
    return [];
  }
}
