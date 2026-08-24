import type {
  ChatMessage,
  Citation,
  KnowledgeDocument,
  MemoryItem,
  MemoryType,
  Plan,
  ReasoningStep,
  TaskStatus,
} from '../types/domain';
import { clearStoredSession, getStoredSession, type StoredSession } from './session';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1';

interface ApiErrorPayload {
  error?: { code?: string; message?: string; trace_id?: string };
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code = 'UNKNOWN_ERROR',
    readonly traceId?: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}, authenticated = true): Promise<T> {
  const session = getStoredSession();
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (authenticated && session?.accessToken) {
    headers.set('Authorization', `Bearer ${session.accessToken}`);
  }
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as ApiErrorPayload;
    if (response.status === 401) {
      clearStoredSession();
      window.dispatchEvent(new Event('workplace-agent:unauthorized'));
    }
    throw new ApiError(
      payload.error?.message ?? '请求失败，请稍后重试',
      response.status,
      payload.error?.code,
      payload.error?.trace_id,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function toSession(payload: {
  access_token: string;
  user: { id: string; email: string; display_name: string };
}): StoredSession {
  return {
    accessToken: payload.access_token,
    user: {
      id: payload.user.id,
      email: payload.user.email,
      displayName: payload.user.display_name,
    },
  };
}

function toMemory(item: Record<string, unknown>): MemoryItem {
  return {
    id: String(item.id),
    type: item.type as MemoryType,
    content: String(item.content),
    source: String(item.source),
    active: Boolean(item.active),
    pinned: Boolean(item.pinned),
    updatedAt: new Date(String(item.updated_at)).toLocaleString('zh-CN'),
  };
}

function toPlan(item: Record<string, unknown>): Plan {
  const tasks = item.tasks as Array<Record<string, unknown>>;
  return {
    id: String(item.id),
    title: String(item.title),
    goal: String(item.goal),
    deadline: item.deadline ? String(item.deadline) : '',
    status: item.status as Plan['status'],
    tasks: tasks.map((task) => ({
      id: String(task.id),
      title: String(task.title),
      description: String(task.description),
      status: task.status as TaskStatus,
      priority: task.priority as 'high' | 'medium' | 'low',
      estimatedMinutes: Number(task.estimated_minutes),
      dueAt: task.due_at ? String(task.due_at) : '',
      doneDefinition: String(task.done_definition),
    })),
  };
}

export const apiClient = {
  async register(values: { email: string; password: string; displayName: string }) {
    const payload = await request<{
      access_token: string;
      user: { id: string; email: string; display_name: string };
    }>(
      '/auth/register',
      {
        method: 'POST',
        body: JSON.stringify({
          email: values.email,
          password: values.password,
          display_name: values.displayName,
        }),
      },
      false,
    );
    return toSession(payload);
  },
  async login(values: { email: string; password: string }) {
    const payload = await request<{
      access_token: string;
      user: { id: string; email: string; display_name: string };
    }>('/auth/login', { method: 'POST', body: JSON.stringify(values) }, false);
    return toSession(payload);
  },
  async getConversations() {
    return request<Array<{ id: string; title: string; mode: string; created_at: string }>>(
      '/conversations',
    );
  },
  async createConversation(title = '新对话') {
    return request<{ id: string; title: string; mode: string; created_at: string }>(
      '/conversations',
      { method: 'POST', body: JSON.stringify({ title, mode: 'standard' }) },
    );
  },
  async getMessages(conversationId: string): Promise<ChatMessage[]> {
    const items = await request<
      Array<{
        id: string;
        role: 'user' | 'assistant';
        content: string;
        created_at: string;
        citations: Array<{
          id: string;
          title: string;
          url: string;
          snippet: string;
          source: string;
          published_at?: string;
        }>;
        reasoning_steps: Array<{
          id: string;
          title: string;
          detail: string;
          status: ReasoningStep['status'];
          kind: ReasoningStep['kind'];
          elapsed_ms?: number;
        }>;
      }>
    >(`/conversations/${conversationId}/messages`);
    return items.map((item) => ({
      id: item.id,
      role: item.role,
      content: item.content,
      createdAt: new Date(item.created_at).toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
      }),
      citations: item.citations.map((citation) => ({
        id: citation.id,
        title: citation.title,
        url: citation.url,
        snippet: citation.snippet,
        source: citation.source,
        publishedAt: citation.published_at,
      })),
      reasoningSteps: item.reasoning_steps.map((step) => ({
        id: step.id,
        title: step.title,
        detail: step.detail,
        status: step.status,
        kind: step.kind,
        elapsedMs: Number(step.elapsed_ms ?? 0),
      })),
    }));
  },
  async streamMessage(
    conversationId: string,
    content: string,
    handlers: {
      onStarted: (id: string) => void;
      onDelta: (text: string) => void;
      onToolStarted?: (tool: string) => void;
      onToolCompleted?: (tool: string, resultCount: number) => void;
      onCitations?: (items: Citation[]) => void;
      onReasoningStep?: (step: ReasoningStep) => void;
    },
    signal: AbortSignal,
  ) {
    const session = getStoredSession();
    const response = await fetch(
      `${API_BASE_URL}/conversations/${conversationId}/messages:stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${session?.accessToken ?? ''}`,
        },
        body: JSON.stringify({ content }),
        signal,
      },
    );
    if (!response.ok || !response.body) throw new ApiError('发送消息失败', response.status);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() ?? '';
      for (const block of blocks) {
        const event = block.match(/^event: (.+)$/m)?.[1];
        const dataText = block.match(/^data: (.+)$/m)?.[1];
        if (!event || !dataText) continue;
        const data = JSON.parse(dataText) as Record<string, unknown>;
        if (event === 'message.started') handlers.onStarted(String(data.message_id));
        if (event === 'message.delta') handlers.onDelta(String(data.text));
        if (event === 'tool.started') handlers.onToolStarted?.(String(data.tool));
        if (event === 'tool.completed') {
          handlers.onToolCompleted?.(String(data.tool), Number(data.result_count ?? 0));
        }
        if (event === 'citations') {
          const items = (data.items as Array<Record<string, unknown>>).map((item) => ({
            id: String(item.id),
            title: String(item.title),
            url: String(item.url),
            snippet: String(item.snippet),
            source: String(item.source),
            publishedAt: item.published_at ? String(item.published_at) : undefined,
          }));
          handlers.onCitations?.(items);
        }
        if (event === 'reasoning.step') {
          handlers.onReasoningStep?.({
            id: String(data.id),
            title: String(data.title),
            detail: String(data.detail),
            status: data.status as ReasoningStep['status'],
            kind: data.kind as ReasoningStep['kind'],
            elapsedMs: Number(data.elapsed_ms ?? 0),
          });
        }
        if (event === 'error') throw new ApiError(String(data.message), 502, String(data.code));
      }
    }
  },
  async getMemories() {
    const items = await request<Array<Record<string, unknown>>>('/memories');
    return items.map(toMemory);
  },
  async createMemory(values: { type: MemoryType; content: string; source?: string }) {
    const candidate = await request<Record<string, unknown>>('/memory-candidates', {
      method: 'POST',
      body: JSON.stringify(values),
    });
    const memory = await request<Record<string, unknown>>(
      `/memory-candidates/${String(candidate.id)}:confirm`,
      { method: 'POST', body: JSON.stringify({}) },
    );
    return toMemory(memory);
  },
  async updateMemory(id: string, patch: Partial<MemoryItem>) {
    const payload = {
      content: patch.content,
      active: patch.active,
      pinned: patch.pinned,
    };
    return toMemory(
      await request<Record<string, unknown>>(`/memories/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      }),
    );
  },
  async deleteMemory(id: string) {
    return request<void>(`/memories/${id}`, { method: 'DELETE' });
  },
  async getDocuments(): Promise<KnowledgeDocument[]> {
    const items = await request<Array<Record<string, unknown>>>('/knowledge/documents');
    return items.map((item) => ({
      id: String(item.id),
      title: String(item.title),
      source: String(item.source),
      trustLevel: item.trust_level as 'A' | 'B' | 'C',
      status: item.status as KnowledgeDocument['status'],
      chunks: Number(item.chunks),
      updatedAt: new Date(String(item.created_at)).toLocaleString('zh-CN'),
    }));
  },
  async uploadDocument(file: File) {
    const form = new FormData();
    form.set('file', file);
    form.set('source', '用户上传');
    return request('/knowledge/documents', { method: 'POST', body: form });
  },
  async getPlans() {
    const items = await request<Array<Record<string, unknown>>>('/plans');
    return items.map(toPlan);
  },
  async createPlan(values: { goal: string; deadline?: string }) {
    const draft = await request<Record<string, unknown>>('/plans:draft', {
      method: 'POST',
      body: JSON.stringify({ goal: values.goal, deadline: values.deadline || null }),
    });
    const plan = await request<Record<string, unknown>>(
      `/plan-drafts/${String(draft.id)}:confirm`,
      {
        method: 'POST',
        body: JSON.stringify({ confirmation_token: draft.confirmation_token }),
      },
    );
    return toPlan(plan);
  },
  async updateTask(taskId: string, status: TaskStatus) {
    return request(`/tasks/${taskId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
  },
};
