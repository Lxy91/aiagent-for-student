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
  attachments?: ChatAttachment[];
  generatedImages?: GeneratedImage[];
  generatedArtifacts?: GeneratedArtifact[];
  tokenUsage?: TokenUsage;
}

export interface TokenUsage {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  estimated: boolean;
}

export interface ChatAttachment {
  id: string;
  title: string;
  materialType: MaterialType;
  mimeType: string;
  status: 'ready' | 'needs_confirmation';
}

export interface GeneratedImage {
  id: string;
  url: string;
  prompt: string;
  model: string;
}

export interface GeneratedArtifact {
  id: string;
  filename: string;
  artifactType: 'docx' | 'xlsx';
  mimeType: string;
  sizeBytes: number;
}

export interface Conversation {
  id: string;
  title: string;
  mode: string;
  is_pinned: boolean;
  is_archived: boolean;
  created_at: string;
}

export interface ConversationContext {
  messageCount: number;
  estimatedTokens: number;
  tokenBudget: number;
  trimmedCount: number;
  compressedAt?: string;
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

export type MaterialType = 'audio' | 'image' | 'document' | 'spreadsheet' | 'text';
export type MaterialStatus = 'ready' | 'needs_confirmation' | 'blocked';

export interface MeetingMinutes {
  id: string;
  summary: string;
  actionItems: string[];
  pendingFacts: string[];
}

export interface WorkMaterial {
  id: string;
  title: string;
  materialType: MaterialType;
  mimeType: string;
  sizeBytes: number;
  purpose: string;
  status: MaterialStatus;
  privacyStatus: 'clear' | 'redacted' | 'review_required';
  contentExcerpt: string;
  createdAt: string;
  minutes?: MeetingMinutes;
}

export interface SourceReference {
  type: 'task' | 'material';
  id: string;
  title: string;
}

export interface ProgressReport {
  id: string;
  periodType: 'weekly' | 'monthly';
  periodStart: string;
  periodEnd: string;
  title: string;
  sections: Record<string, string[]>;
  sources: SourceReference[];
  createdAt: string;
}

export interface GrowthEvidence {
  id: string;
  capability: string;
  summary: string;
  sourceType: 'material' | 'task' | 'feedback';
  sourceId: string;
  sourceTitle: string;
  observedAt: string;
}

export interface LearningRecommendation {
  capability: string;
  reason: string;
  nextAction: string;
  evidenceCount: number;
}

export interface GrowthProfile {
  evidence: GrowthEvidence[];
  recommendations: LearningRecommendation[];
}
