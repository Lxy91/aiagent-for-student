export type MessageRole = 'user' | 'assistant';

export interface Citation {
  id: string;
  title: string;
  source: string;
  url: string;
  snippet: string;
  publishedAt?: string;
}

export interface ReasoningStep {
  id: string;
  title: string;
  detail: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  kind: 'analysis' | 'plan' | 'tool' | 'answer';
  elapsedMs?: number;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  createdAt: string;
  citations?: Citation[];
  reasoningSteps?: ReasoningStep[];
}

export interface Conversation {
  id: string;
  title: string;
  mode: string;
  is_pinned: boolean;
  is_archived: boolean;
  created_at: string;
}

export type MemoryType = 'profile' | 'preference' | 'goal' | 'experience';

export interface MemoryItem {
  id: string;
  type: MemoryType;
  content: string;
  source: string;
  updatedAt: string;
  pinned: boolean;
  active: boolean;
}

export type TaskStatus = 'todo' | 'doing' | 'done' | 'cancelled';
export type TaskPriority = 'high' | 'medium' | 'low';

export interface PlanTask {
  id: string;
  title: string;
  description: string;
  status: TaskStatus;
  priority: TaskPriority;
  estimatedMinutes: number;
  dueAt: string;
  doneDefinition: string;
}

export interface Plan {
  id: string;
  title: string;
  goal: string;
  deadline: string;
  status: 'draft' | 'active' | 'completed' | 'cancelled';
  tasks: PlanTask[];
}

export type DocumentStatus = 'ready' | 'processing' | 'failed';

export interface KnowledgeDocument {
  id: string;
  title: string;
  source: string;
  trustLevel: 'A' | 'B' | 'C';
  status: DocumentStatus;
  chunks: number;
  updatedAt: string;
}
