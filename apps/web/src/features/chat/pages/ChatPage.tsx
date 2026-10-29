import {
  ArrowRightOutlined,
  AudioOutlined,
  CheckCircleFilled,
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  DislikeOutlined,
  FileImageOutlined,
  FileTextOutlined,
  LikeOutlined,
  GlobalOutlined,
  LinkOutlined,
  LoadingOutlined,
  MoreOutlined,
  PaperClipOutlined,
  PlusOutlined,
  PushpinFilled,
  PushpinOutlined,
  EditOutlined,
  UnorderedListOutlined,
  InboxOutlined,
  SendOutlined,
  StopOutlined,
  TableOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  App,
  Avatar,
  Button,
  Collapse,
  Dropdown,
  Input,
  Modal,
  Popconfirm,
  Progress,
  Segmented,
  Space,
  Tag,
  Tooltip,
  Upload,
} from 'antd';
import type { ReactNode } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import { useNavigate } from 'react-router-dom';
import remarkGfm from 'remark-gfm';
import { BrandMark } from '../../../components/BrandMark';
import { StateCard } from '../../../components/StateCard';
import { apiClient } from '../../../services/api-client';
import type {
  ChatMessage,
  Conversation,
  ConversationContext,
  ExecutionPlan,
  ExecutionInterrupt,
  CheckpointResume,
  GeneratedArtifact,
  MaterialType,
  ReasoningStep,
  WorkMaterial,
} from '../../../types/domain';

const starterPrompts = ['怎么向领导澄清任务？', '帮我准备第一次周会', '把模糊目标拆成计划'];
const { Dragger } = Upload;
const attachmentAccept = '.mp3,.wav,.m4a,.png,.jpg,.jpeg,.pdf,.docx,.xlsx,.xls,.csv,.md,.txt';
const attachmentIcons: Record<MaterialType, ReactNode> = {
  audio: <AudioOutlined />,
  image: <FileImageOutlined />,
  document: <FileTextOutlined />,
  spreadsheet: <TableOutlined />,
  text: <FileTextOutlined />,
};

interface ConversationGeneration {
  assistantId: string;
  toolStatus?: string;
  phaseLabel?: string;
}

const markdownComponents: Components = {
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="markdown-table-wrap">
      <table>{children}</table>
    </div>
  ),
};

function AssistantMarkdown({ content }: { content: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents} skipHtml>
        {content}
      </ReactMarkdown>
    </div>
  );
}

function problemSummaries(issues: string[]): string[] {
  const result: string[] = [];
  for (const issue of issues) {
    const text = issue.replace(/\s+/g, ' ');
    const summary =
      text.includes('截断') && text.includes('关键路径') && text.includes('状态快照')
        ? '方案正文被截断，关键路径和状态快照尚未输出。'
        : text.includes('截断')
          ? '部分正文被截断，方案尚未输出完整。'
          : text.split(/[。；;\n]/)[0].slice(0, 100);
    if (/(.{6,60})\1{2}/.test(summary)) continue;
    if (
      summary &&
      !result.includes(summary) &&
      !(summary.includes('截断') && result.some((item) => item.includes('截断')))
    )
      result.push(summary);
    if (result.length === 2) break;
  }
  return result;
}

function isDraftResponse(item: ChatMessage): boolean {
  if (item.deliveryStatus) return ['draft', 'waiting_user'].includes(item.deliveryStatus);
  return Boolean(item.executionPlan && item.executionPlan.acceptance_status !== 'passed');
}

function AssistantResponse({
  item,
  active,
  phase,
}: {
  item: ChatMessage;
  active: boolean;
  phase?: string;
}) {
  if (isDraftResponse(item)) {
    const draft = item.draftContent ?? (item.deliveryStatus ? undefined : item.content);
    return (
      <>
        <p className="answer-phase" role="status">
          {active
            ? (phase ?? '正在处理任务，检查后展示正文。')
            : item.executionPlan?.acceptance_status === 'failed'
              ? (item.executionPlan.explanation ?? '本次未通过检查，草稿和进度已保存。')
              : '方案尚未定稿，已保存草稿和进度。'}
        </p>
        {draft ? (
          <Collapse
            className="draft-preview"
            size="small"
            items={[
              {
                key: 'draft',
                label: '查看未定稿草稿（仅供参考）',
                children: (
                  <div className="draft-preview-body">
                    <AssistantMarkdown content={draft} />
                  </div>
                ),
              },
            ]}
          />
        ) : null}
      </>
    );
  }
  if (item.content) return <AssistantMarkdown content={item.content} />;
  return (
    <p className="answer-phase" role="status">
      {active ? (phase ?? '正在执行任务…') : '任务进度已保存。'}
    </p>
  );
}

function interruptCopy(question: ExecutionInterrupt, issues: string[] = []): ExecutionInterrupt {
  const problems = problemSummaries(question.problems?.length ? question.problems : issues);
  if (question.kind === 'acceptance' && problems.some((item) => item.includes('截断'))) {
    return {
      ...question,
      problems,
      question: '要从断点继续补完方案吗？',
      reason: '草稿已经保存，但还没有写完整。',
      recommendation: '建议接着补完缺失章节，保留已经完成的内容。',
      options: ['继续补完方案（推荐）', '我来调整输出范围'],
    };
  }
  if (
    question.kind === 'acceptance' &&
    (question.reason.length > 220 || question.question.length > 160)
  ) {
    return {
      ...question,
      problems,
      question: '要先保留原来的要求，由我继续调整方案吗？',
      reason: '方案还有需要修正的地方，计算和排期问题由我处理。',
      recommendation: '建议先保留你的原要求，我会自动修订后重新检查。',
      options: ['保持原要求，继续自动调整（推荐）', '我来补充优先级'],
    };
  }
  return {
    ...question,
    problems,
    question: question.question.slice(0, 160),
    reason:
      question.reason.length > 220 ? '当前进度已保存，确认这一项安排后即可继续。' : question.reason,
    recommendation: question.recommendation?.slice(0, 160),
    options: question.options.slice(0, 3).map((option) => option.slice(0, 80)),
  };
}

function ExecutionTrace({ steps }: { steps: ReasoningStep[] }) {
  const displaySteps = useMemo(() => {
    const items: ReasoningStep[] = [];
    let legacy: ReasoningStep | undefined;
    let count = 0;
    const flush = () => {
      if (legacy)
        items.push({
          ...legacy,
          kind: 'tool',
          detail: `execution.update_plan：计划更新（${count > 1 ? `合并 ${count} 条历史记录` : '历史记录'}）。`,
        });
      legacy = undefined;
      count = 0;
    };
    for (const step of steps) {
      if (step.detail === '我会更新任务计划，再推进当前步骤。') {
        legacy = step;
        count += 1;
      } else {
        flush();
        items.push(
          step.detail === '先将任务拆成可逐步完成的执行计划。'
            ? {
                ...step,
                kind: 'tool',
                detail: 'execution.update_plan：准备创建任务清单（历史记录）。',
              }
            : step,
        );
      }
    }
    flush();
    return items;
  }, [steps]);
  const latestElapsed = Math.max(0, ...steps.map((step) => step.elapsedMs ?? 0));
  const isRunning = steps.some((step) => step.status === 'running');
  const [elapsed, setElapsed] = useState(latestElapsed);

  useEffect(() => {
    setElapsed(latestElapsed);
    if (!isRunning) return undefined;
    const timer = window.setInterval(() => {
      setElapsed((current) => Math.max(current + 1000, latestElapsed));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [isRunning, latestElapsed]);

  const totalSeconds = Math.max(0, Math.round(elapsed / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const elapsedLabel = minutes ? `${minutes}分钟 ${seconds}秒` : `${seconds}秒`;

  return (
    <Collapse
      className="reasoning-trace"
      ghost
      size="small"
      defaultActiveKey={['trace']}
      items={[
        {
          key: 'trace',
          label: (
            <span className="reasoning-label">
              {steps.some((step) => step.status === 'running') ? <LoadingOutlined spin /> : null}
              耗时 {elapsedLabel}
            </span>
          ),
          children: (
            <div className="reasoning-log">
              {displaySteps.map((step) =>
                step.kind === 'tool' ? (
                  <div key={step.id} className={`reasoning-tool-row ${step.status}`} role="status">
                    {step.status === 'running' ? (
                      <LoadingOutlined spin />
                    ) : step.detail.includes('web.search') ? (
                      <GlobalOutlined />
                    ) : (
                      <ToolOutlined />
                    )}
                    <span>{step.detail}</span>
                  </div>
                ) : (
                  <p key={step.id} className={`reasoning-narrative ${step.status}`}>
                    {step.id === 'task-acceptance' && step.detail.length > 180
                      ? '方案还需要调整，具体问题由助手继续处理。'
                      : step.detail}
                  </p>
                ),
              )}
            </div>
          ),
        },
      ]}
    />
  );
}

function TaskPlan({
  plan,
  active,
  onContinue,
  disabled,
}: {
  plan: ExecutionPlan;
  active: boolean;
  onContinue: () => void;
  disabled: boolean;
}) {
  const completed = plan.tasks.filter((task) => task.status === 'completed').length;
  const statusLabel =
    plan.status === 'cancelled'
      ? '已结束'
      : plan.status === 'waiting_user'
        ? '等待你的答复'
        : plan.status === 'completed'
          ? '验收通过'
          : completed === plan.tasks.length && active
            ? '待验收'
            : active
              ? '执行中'
              : '待继续';
  const labels = {
    pending: '待处理',
    running: active ? '进行中' : '待继续',
    completed: '已完成',
    blocked: '受阻',
  };
  return (
    <Collapse
      className="execution-plan"
      size="small"
      defaultActiveKey={['plan']}
      items={[
        {
          key: 'plan',
          label: (
            <Space>
              <UnorderedListOutlined />
              <strong>任务计划</strong>
              <span>
                {completed}/{plan.tasks.length} 步骤完成
              </span>
              <Tag
                color={plan.status === 'completed' ? 'success' : active ? 'processing' : 'warning'}
              >
                {statusLabel}
              </Tag>
            </Space>
          ),
          children: (
            <div className="execution-plan-body" aria-live="polite">
              {plan.explanation ? <p>{plan.explanation}</p> : null}
              <ol>
                {plan.tasks.map((task) => (
                  <li key={task.id} className={task.status}>
                    <div>
                      <span>
                        {task.status === 'completed' ? (
                          <CheckCircleFilled />
                        ) : task.status === 'running' && active ? (
                          <LoadingOutlined spin />
                        ) : null}
                      </span>
                      <strong>{task.title}</strong>
                      <Tag>{labels[task.status]}</Tag>
                    </div>
                    {task.result ? <p>{task.result}</p> : null}
                  </li>
                ))}
              </ol>
              {plan.acceptance_issues?.length ? (
                <p role="status">方案还需要调整，具体计算和排期问题由助手处理。</p>
              ) : null}
              {!active && plan.status !== 'completed' && plan.status !== 'cancelled' ? (
                <Button size="small" onClick={onContinue} disabled={disabled}>
                  继续执行剩余步骤
                </Button>
              ) : null}
            </div>
          ),
        },
      ]}
    />
  );
}

export function ChatPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState('');
  const [interruptDialog, setInterruptDialog] = useState<ExecutionInterrupt>();
  const [interruptAnswer, setInterruptAnswer] = useState('');
  const [interruptOption, setInterruptOption] = useState('');
  const [dismissedInterrupts, setDismissedInterrupts] = useState<Record<string, boolean>>({});
  const [usePlan, setUsePlan] = useState(false);
  const [attachments, setAttachments] = useState<WorkMaterial[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [conversationId, setConversationId] = useState<string>();
  const [renamingConversation, setRenamingConversation] = useState<Conversation>();
  const [renameDraft, setRenameDraft] = useState('');
  const [generations, setGenerations] = useState<Record<string, ConversationGeneration>>({});
  const generationControllersRef = useRef(new Map<string, AbortController>());
  const resumedInternalRepairsRef = useRef(new Set<string>());
  const conversations = useQuery({
    queryKey: ['conversations'],
    queryFn: apiClient.getConversations,
  });
  const createConversation = useMutation({
    mutationFn: () => apiClient.createConversation(),
    onSuccess: async (conversation) => {
      queryClient.setQueryData<ChatMessage[]>(['messages', conversation.id], []);
      setConversationId(conversation.id);
      await queryClient.invalidateQueries({ queryKey: ['conversations'] });
    },
  });
  const updateConversation = useMutation({
    mutationFn: ({
      id,
      changes,
    }: {
      id: string;
      changes: { title?: string; is_pinned?: boolean; is_archived?: boolean };
    }) => apiClient.updateConversation(id, changes),
    onSuccess: async (updated) => {
      queryClient.setQueryData<Conversation[]>(['conversations'], (items = []) =>
        items
          .map((item) => (item.id === updated.id ? updated : item))
          .filter((item) => !item.is_archived)
          .sort(
            (left, right) =>
              Number(right.is_pinned) - Number(left.is_pinned) ||
              new Date(right.created_at).getTime() - new Date(left.created_at).getTime(),
          ),
      );
      if (updated.is_archived && conversationId === updated.id) setConversationId(undefined);
      await queryClient.invalidateQueries({ queryKey: ['conversations'] });
    },
    onError: (error) => {
      message.error(error instanceof Error ? error.message : '操作失败');
    },
  });
  const messages = useQuery({
    queryKey: ['messages', conversationId],
    queryFn: () => apiClient.getMessages(conversationId!),
    enabled: Boolean(conversationId),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const conversationContext = useQuery({
    queryKey: ['conversation-context', conversationId],
    queryFn: () => apiClient.getConversationContext(conversationId!),
    enabled: Boolean(conversationId),
  });
  const compressContext = useMutation({
    mutationFn: (id: string) => apiClient.compressConversationContext(id),
    onSuccess: (context, id) => {
      queryClient.setQueryData(['conversation-context', id], context);
      message.success('上下文已压缩为摘要，聊天记录仍会保留');
    },
    onError: (error) => {
      message.error(error instanceof Error ? error.message : '上下文压缩失败');
    },
  });

  useEffect(() => {
    if (!conversationId && conversations.data?.length) {
      setConversationId(conversations.data[0].id);
    }
  }, [conversationId, conversations.data]);

  useEffect(
    () => () => {
      generationControllersRef.current.forEach((controller) => controller.abort());
      generationControllersRef.current.clear();
    },
    [],
  );

  const selectedConversation = useMemo(
    () => conversations.data?.find((item) => item.id === conversationId),
    [conversationId, conversations.data],
  );
  const localMessages = messages.data ?? [];
  const currentGeneration = conversationId ? generations[conversationId] : undefined;
  const isGenerating = Boolean(currentGeneration);
  const toolStatus = currentGeneration?.toolStatus;
  const planMessage = [...localMessages].reverse().find((item) => item.executionPlan);
  const pendingQuestion = [...localMessages]
    .reverse()
    .find((item) => item.executionInterrupt?.status === 'waiting')?.executionInterrupt;

  const showInterrupt = (question: ExecutionInterrupt) => {
    setInterruptAnswer('');
    setInterruptOption('');
    setInterruptDialog(
      interruptCopy(
        question,
        localMessages.find((item) => item.executionInterrupt?.id === question.id)?.executionPlan
          ?.acceptance_issues,
      ),
    );
  };
  const dialogCopy = interruptDialog
    ? interruptCopy(
        interruptDialog,
        localMessages.find((item) => item.executionInterrupt?.id === interruptDialog.id)
          ?.executionPlan?.acceptance_issues,
      )
    : undefined;

  useEffect(() => {
    if (
      !isGenerating &&
      pendingQuestion &&
      pendingQuestion.requires_input !== false &&
      !dismissedInterrupts[pendingQuestion.id] &&
      interruptDialog?.id !== pendingQuestion.id
    )
      showInterrupt(pendingQuestion);
  }, [pendingQuestion, isGenerating, dismissedInterrupts, interruptDialog?.id]);

  useEffect(() => {
    setInterruptDialog(undefined);
  }, [conversationId]);

  const ensureConversation = async () => {
    if (conversationId) return conversationId;
    const conversation = await apiClient.createConversation();
    queryClient.setQueryData<ChatMessage[]>(['messages', conversation.id], []);
    setConversationId(conversation.id);
    await queryClient.invalidateQueries({ queryKey: ['conversations'] });
    return conversation.id;
  };

  const updateCachedMessages = (
    targetId: string,
    update: (items: ChatMessage[]) => ChatMessage[],
  ) => {
    queryClient.setQueryData<ChatMessage[]>(['messages', targetId], (items = []) => update(items));
  };

  const updateGenerationStatus = (targetId: string, assistantId: string, toolStatus: string) => {
    setGenerations((items) => {
      const current = items[targetId];
      if (current?.assistantId !== assistantId) return items;
      return { ...items, [targetId]: { ...current, toolStatus } };
    });
  };

  const uploadAttachment = async (file: File) => {
    if (attachments.length >= 5) {
      message.warning('每条消息最多添加 5 个附件');
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      message.error('单个附件不能超过 20 MB');
      return;
    }
    setIsUploading(true);
    try {
      const material = await apiClient.uploadMaterial(file, 'conversation');
      if (material.status === 'blocked') {
        message.error('附件包含高风险隐私信息，已阻止添加');
        return;
      }
      setAttachments((items) => [...items, material]);
      message.success(
        material.status === 'needs_confirmation'
          ? '附件已添加，但暂未提取到可读取的文字'
          : '附件已解析并添加到对话',
      );
      await queryClient.invalidateQueries({ queryKey: ['materials'] });
    } catch (error) {
      message.error(error instanceof Error ? error.message : '附件上传失败');
    } finally {
      setIsUploading(false);
    }
  };

  const sendMessage = async (
    content = draft,
    planRequested = usePlan,
    resume?: CheckpointResume,
    automatic = false,
  ) => {
    const effectiveResume =
      resume ??
      (pendingQuestion && !pendingQuestion.id.startsWith('local-')
        ? { checkpointId: pendingQuestion.id, action: 'continue' as const }
        : undefined);
    const trimmedContent = content.trim();
    const queuedAttachments = automatic ? [] : attachments;
    if (!trimmedContent && !queuedAttachments.length) return;
    const targetId = await ensureConversation();
    if (generationControllersRef.current.has(targetId)) return;
    await queryClient.cancelQueries({ queryKey: ['messages', targetId], exact: true });
    const now = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    const assistantId = `assistant-${Date.now()}`;
    updateCachedMessages(targetId, (items) => [
      ...items,
      {
        id: `user-${Date.now()}`,
        role: 'user',
        content: trimmedContent,
        createdAt: now,
        attachments: queuedAttachments.map((item) => ({
          id: item.id,
          title: item.title,
          materialType: item.materialType,
          mimeType: item.mimeType,
          status: item.status === 'ready' ? 'ready' : 'needs_confirmation',
        })),
      },
      { id: assistantId, role: 'assistant', content: '', createdAt: now },
    ]);
    if (!automatic) {
      setDraft('');
      setAttachments([]);
    }
    const controller = new AbortController();
    generationControllersRef.current.set(targetId, controller);
    setGenerations((items) => ({ ...items, [targetId]: { assistantId } }));
    let streamedText = '';
    let interrupted = false;
    try {
      await apiClient.streamMessage(
        targetId,
        trimmedContent,
        queuedAttachments.map((item) => item.id),
        {
          onStarted: () => {
            void queryClient.invalidateQueries({ queryKey: ['conversations'] });
          },
          onPlan: (executionPlan) =>
            updateCachedMessages(targetId, (items) =>
              items.map((item) => (item.id === assistantId ? { ...item, executionPlan } : item)),
            ),
          onInterrupt: (executionInterrupt) => {
            interrupted = true;
            updateCachedMessages(targetId, (items) =>
              items.map((item) =>
                item.id === assistantId
                  ? {
                      ...item,
                      executionInterrupt,
                      deliveryStatus: 'waiting_user',
                      draftContent: item.content || item.draftContent,
                    }
                  : item,
              ),
            );
          },
          onDelta: (text) => {
            streamedText += text;
            updateCachedMessages(targetId, (items) =>
              items.map((item) =>
                item.id === assistantId ? { ...item, content: item.content + text } : item,
              ),
            );
          },
          onPhase: (phase, detail) => {
            setGenerations((items) =>
              items[targetId]?.assistantId === assistantId
                ? {
                    ...items,
                    [targetId]: { ...items[targetId], phaseLabel: detail, toolStatus: undefined },
                  }
                : items,
            );
            updateCachedMessages(targetId, (items) =>
              items.map((item) =>
                item.id === assistantId
                  ? { ...item, deliveryStatus: phase === 'delivering' ? 'final' : 'draft' }
                  : item,
              ),
            );
          },
          onReplace: (text) => {
            streamedText = text;
            updateCachedMessages(targetId, (items) =>
              items.map((item) => (item.id === assistantId ? { ...item, content: text } : item)),
            );
          },
          onToolStarted: (tool) =>
            updateGenerationStatus(
              targetId,
              assistantId,
              tool === 'web.search' ? '正在联网检索并核对来源…' : '正在调用工具…',
            ),
          onToolCompleted: (tool, resultCount) =>
            updateGenerationStatus(
              targetId,
              assistantId,
              tool === 'web.search' ? `已检索并筛选 ${resultCount} 个来源` : '工具调用已完成',
            ),
          onToolFailed: (tool, reason) =>
            updateGenerationStatus(targetId, assistantId, `${tool} 失败：${reason}`),
          onCitations: (citations) =>
            updateCachedMessages(targetId, (items) =>
              items.map((item) => (item.id === assistantId ? { ...item, citations } : item)),
            ),
          onImages: (generatedImages) =>
            updateCachedMessages(targetId, (items) =>
              items.map((item) => (item.id === assistantId ? { ...item, generatedImages } : item)),
            ),
          onArtifacts: (generatedArtifacts) =>
            updateCachedMessages(targetId, (items) =>
              items.map((item) =>
                item.id === assistantId ? { ...item, generatedArtifacts } : item,
              ),
            ),
          onReasoningStep: (step) =>
            updateCachedMessages(targetId, (items) =>
              items.map((item) => {
                if (item.id !== assistantId) return item;
                const reasoningSteps = [...(item.reasoningSteps ?? [])];
                const existingIndex = reasoningSteps.findIndex((item) => item.id === step.id);
                if (existingIndex >= 0) reasoningSteps[existingIndex] = step;
                else reasoningSteps.push(step);
                return { ...item, reasoningSteps };
              }),
            ),
          onContextUsage: (context) =>
            queryClient.setQueryData<ConversationContext>(
              ['conversation-context', targetId],
              context,
            ),
        },
        controller.signal,
        planRequested || Boolean(effectiveResume),
        effectiveResume,
      );
      await queryClient.invalidateQueries({ queryKey: ['messages', targetId] });
      await queryClient.invalidateQueries({ queryKey: ['conversation-context', targetId] });
    } catch (error) {
      if (!controller.signal.aborted && !interrupted) {
        const connectionQuestion: ExecutionInterrupt = {
          id: `local-${assistantId}`,
          kind: 'error',
          status: 'waiting',
          question: '连接中断，要根据已保存的会话重试，还是补充要求后继续？',
          reason: `${error instanceof Error ? error.message : '连接中断'}。未收到服务端待答复检查点，重试将参考已保存的会话记录。`,
          options: ['根据已保存记录继续', '补充要求后继续'],
        };
        updateCachedMessages(targetId, (items) =>
          items.map((item) =>
            item.id === assistantId ? { ...item, executionInterrupt: connectionQuestion } : item,
          ),
        );
        showInterrupt(connectionQuestion);
        if (streamedText) {
          message.warning('连接中断，已保留已经生成的内容');
          updateCachedMessages(targetId, (items) =>
            items.map((item) =>
              item.id === assistantId
                ? {
                    ...item,
                    content: `${item.content}\n\n> 连接中断，已保留已经生成的内容，可以继续提问。`,
                  }
                : item,
            ),
          );
        } else {
          message.error(error instanceof Error ? error.message : '消息发送失败');
          updateCachedMessages(targetId, (items) =>
            items.filter(
              (item) => item.id !== assistantId || item.executionPlan || item.executionInterrupt,
            ),
          );
        }
      }
    } finally {
      void queryClient.invalidateQueries({ queryKey: ['messages', targetId] });
      if (generationControllersRef.current.get(targetId) === controller) {
        generationControllersRef.current.delete(targetId);
        setGenerations((items) => {
          if (items[targetId]?.assistantId !== assistantId) return items;
          const next = { ...items };
          delete next[targetId];
          return next;
        });
      }
    }
  };

  useEffect(() => {
    if (
      isGenerating ||
      !pendingQuestion ||
      pendingQuestion.requires_input !== false ||
      resumedInternalRepairsRef.current.has(pendingQuestion.id)
    )
      return;
    resumedInternalRepairsRef.current.add(pendingQuestion.id);
    setInterruptDialog(undefined);
    void sendMessage(
      '保持原始要求，自行修正计算、排期和遗漏并重新验收，无需询问是否继续。',
      true,
      { checkpointId: pendingQuestion.id, action: 'continue' },
      true,
    );
  }, [pendingQuestion, isGenerating]);

  const dismissQuestion = () => {
    if (interruptDialog)
      setDismissedInterrupts((items) => ({ ...items, [interruptDialog.id]: true }));
    setInterruptDialog(undefined);
  };

  const submitQuestion = (action: 'continue' | 'cancel') => {
    if (!interruptDialog || isGenerating) return;
    const answer = [interruptOption, interruptAnswer.trim()].filter(Boolean).join('\n');
    if (action === 'continue' && !answer) return;
    const checkpointId = interruptDialog.id;
    dismissQuestion();
    if (checkpointId.startsWith('local-')) {
      if (action !== 'cancel') void sendMessage(`继续此前未完成的任务。用户答复：${answer}`, true);
      return;
    }
    void sendMessage(action === 'cancel' ? '结束本次任务' : answer, true, { checkpointId, action });
  };

  const stopGenerating = () => {
    if (!conversationId) return;
    generationControllersRef.current.get(conversationId)?.abort();
    message.info('已停止生成');
  };

  const downloadArtifact = async (artifact: GeneratedArtifact) => {
    try {
      await apiClient.downloadArtifact(artifact);
      message.success(`已开始下载 ${artifact.filename}`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '文件下载失败');
    }
  };

  const openRename = (conversation: Conversation) => {
    setRenamingConversation(conversation);
    setRenameDraft(conversation.title);
  };

  const submitRename = async () => {
    const title = renameDraft.trim();
    if (!renamingConversation || !title) {
      message.warning('会话名称不能为空');
      return;
    }
    await updateConversation.mutateAsync({ id: renamingConversation.id, changes: { title } });
    setRenamingConversation(undefined);
  };

  return (
    <div className="chat-page">
      <aside className="conversation-panel">
        <Button
          type="primary"
          block
          icon={<PlusOutlined />}
          loading={createConversation.isPending}
          onClick={() => createConversation.mutate()}
        >
          新建对话
        </Button>
        <div className="conversation-label">最近对话</div>
        <div className="conversation-list">
          {conversations.data?.map((conversation) => (
            <div
              key={conversation.id}
              className={`conversation-item ${conversation.id === conversationId ? 'active' : ''}`}
            >
              <button
                className="conversation-select"
                onClick={() => setConversationId(conversation.id)}
              >
                <span>
                  {conversation.is_pinned ? <PushpinFilled className="conversation-pin" /> : null}
                  {conversation.title}
                </span>
                <small>{new Date(conversation.created_at).toLocaleDateString('zh-CN')}</small>
              </button>
              <Dropdown
                trigger={['click']}
                placement="bottomRight"
                menu={{
                  items: [
                    { key: 'rename', icon: <EditOutlined />, label: '重命名' },
                    {
                      key: 'pin',
                      icon: <PushpinOutlined />,
                      label: conversation.is_pinned ? '取消置顶' : '置顶',
                    },
                    { type: 'divider' },
                    { key: 'archive', icon: <InboxOutlined />, label: '归档', danger: true },
                  ],
                  onClick: ({ key, domEvent }) => {
                    domEvent.stopPropagation();
                    if (key === 'rename') openRename(conversation);
                    if (key === 'pin') {
                      updateConversation.mutate({
                        id: conversation.id,
                        changes: { is_pinned: !conversation.is_pinned },
                      });
                    }
                    if (key === 'archive') {
                      updateConversation.mutate({
                        id: conversation.id,
                        changes: { is_archived: true },
                      });
                    }
                  },
                }}
              >
                <Button
                  className="conversation-more"
                  type="text"
                  size="small"
                  icon={<MoreOutlined />}
                  aria-label={`更多操作：${conversation.title}`}
                  onClick={(event) => event.stopPropagation()}
                />
              </Dropdown>
            </div>
          ))}
        </div>
        <div className="privacy-note">
          <CheckCircleFilled />
          <div>
            <strong>记忆由你控制</strong>
            <span>长期信息保存前都会征得确认</span>
          </div>
        </div>
      </aside>

      <main className="chat-workspace">
        <div className="chat-toolbar">
          <div>
            <h1>{selectedConversation?.title ?? '新对话'}</h1>
            <span>V0.3 · 可追溯资料与成长闭环</span>
          </div>
          <div className="chat-toolbar-actions">
            {conversationId ? (
              <Popconfirm
                title="压缩当前上下文？"
                description="旧内容会整理成摘要，聊天记录保持不变。"
                okText="压缩"
                cancelText="取消"
                onConfirm={() => compressContext.mutate(conversationId)}
              >
                <Tooltip
                  title={
                    isGenerating
                      ? '显示本轮执行上下文，包含工具定义与结果，接近预算会自动整理。手动压缩影响后续请求。'
                      : '显示历史对话占用，点击可手动压缩历史上下文'
                  }
                >
                  <Button
                    type="text"
                    className="context-meter"
                    loading={compressContext.isPending}
                    aria-label="查看并压缩当前上下文"
                  >
                    <Progress
                      type="circle"
                      size={38}
                      percent={Math.min(
                        100,
                        Math.round(
                          ((conversationContext.data?.estimatedTokens ?? 0) /
                            Math.max(1, conversationContext.data?.tokenBudget ?? 1)) *
                            100,
                        ),
                      )}
                      strokeColor="#287565"
                      railColor="#dce7e1"
                      format={(percent) => `${percent ?? 0}%`}
                    />
                    <span className="context-meter-copy">
                      <strong>{isGenerating ? '执行上下文' : '历史上下文'}</strong>
                      <small>
                        {(conversationContext.data?.estimatedTokens ?? 0).toLocaleString()} /{' '}
                        {(conversationContext.data?.tokenBudget ?? 0).toLocaleString()}
                      </small>
                    </span>
                  </Button>
                </Tooltip>
              </Popconfirm>
            ) : null}
            <Segmented
              className="chat-mode-switch"
              options={['标准对话', '临时对话']}
              size="small"
            />
          </div>
        </div>

        <StateCard
          loading={conversations.isLoading || messages.isLoading}
          empty={!localMessages.length}
          emptyText="有什么我可以帮你的吗？"
          emptyClassName="chat-empty-state"
        >
          <div className="message-stream">
            {localMessages.map((item) => (
              <article key={item.id} className={`message-row ${item.role}`}>
                {item.role === 'assistant' ? (
                  <Avatar className="assistant-avatar" icon={<BrandMark />} />
                ) : null}
                <div className="message-content">
                  <div className="message-meta">
                    <strong>{item.role === 'assistant' ? '启程' : '你'}</strong>
                    <span>{item.createdAt}</span>
                  </div>
                  {item.role === 'assistant' && item.reasoningSteps?.length ? (
                    <ExecutionTrace steps={item.reasoningSteps} />
                  ) : null}
                  <div className="message-bubble">
                    {item.role === 'user' && item.attachments?.length ? (
                      <div className="message-attachments">
                        {item.attachments.map((attachment) => (
                          <div className="message-attachment" key={attachment.id}>
                            {attachmentIcons[attachment.materialType]}
                            <span>{attachment.title}</span>
                            {attachment.status === 'needs_confirmation' ? (
                              <Tag color="warning">仅附件</Tag>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : null}
                    {item.role === 'assistant' ? (
                      <AssistantResponse
                        item={item}
                        active={currentGeneration?.assistantId === item.id}
                        phase={currentGeneration?.phaseLabel}
                      />
                    ) : item.content ? (
                      item.content
                        .split('\n')
                        .map((paragraph, index) =>
                          paragraph ? (
                            <p key={`${item.id}-${index}`}>{paragraph}</p>
                          ) : (
                            <br key={index} />
                          ),
                        )
                    ) : null}
                  </div>
                  {item.role === 'assistant' && item.generatedImages?.length ? (
                    <div className="generated-image-list">
                      {item.generatedImages.map((image) => (
                        <figure key={image.id}>
                          <img src={image.url} alt={image.prompt || 'AI 生成图片'} loading="lazy" />
                          <figcaption>
                            <strong>图片说明</strong>
                            <span>{image.prompt}</span>
                            <small>{image.model} 生成</small>
                          </figcaption>
                        </figure>
                      ))}
                    </div>
                  ) : null}
                  {item.role === 'assistant' && item.generatedArtifacts?.length ? (
                    <div className="generated-artifact-list" aria-label="生成的文件">
                      <strong>可下载文件</strong>
                      {item.generatedArtifacts.map((artifact) => (
                        <a
                          key={artifact.id}
                          href={`/api/v1/artifacts/${artifact.id}/download`}
                          onClick={(event) => {
                            event.preventDefault();
                            void downloadArtifact(artifact);
                          }}
                        >
                          {artifact.artifactType === 'xlsx' ? (
                            <TableOutlined />
                          ) : (
                            <FileTextOutlined />
                          )}
                          <span>
                            <strong>{artifact.filename}</strong>
                            <small>
                              {artifact.artifactType === 'xlsx' ? 'Excel 表格' : 'Word 文档'} ·{' '}
                              {Math.max(1, Math.round(artifact.sizeBytes / 1024))} KB
                            </small>
                          </span>
                          <DownloadOutlined />
                        </a>
                      ))}
                    </div>
                  ) : null}
                  {item.role === 'assistant' && item.citations?.length ? (
                    <Collapse
                      className="citation-collapse"
                      ghost
                      size="small"
                      items={[
                        {
                          key: 'sources',
                          label: `查看 ${item.citations.length} 个参考来源`,
                          children: (
                            <div className="citation-list" aria-label="联网来源">
                              {item.citations.map((citation, index) => (
                                <a
                                  key={citation.id}
                                  href={citation.url}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  <Tag>{index + 1}</Tag>
                                  <span>
                                    <strong>{citation.title}</strong>
                                    <small>{citation.source}</small>
                                  </span>
                                  <LinkOutlined />
                                </a>
                              ))}
                            </div>
                          ),
                        },
                      ]}
                    />
                  ) : null}
                  {item.role === 'assistant' && item.content && !isDraftResponse(item) ? (
                    <Space className="message-actions" size={4}>
                      <Tooltip title="复制">
                        <Button type="text" size="small" icon={<CopyOutlined />} />
                      </Tooltip>
                      <Tooltip title="有帮助">
                        <Button type="text" size="small" icon={<LikeOutlined />} />
                      </Tooltip>
                      <Tooltip title="需改进">
                        <Button type="text" size="small" icon={<DislikeOutlined />} />
                      </Tooltip>
                    </Space>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </StateCard>

        <div className="composer-wrap">
          {pendingQuestion && pendingQuestion.requires_input !== false ? (
            <div className="execution-question-banner" role="status">
              <Tag color="warning">等待你的答复</Tag>
              <span>{interruptCopy(pendingQuestion).question}</span>
              <Button
                size="small"
                disabled={isGenerating}
                onClick={() => showInterrupt(pendingQuestion)}
              >
                回答并继续
              </Button>
            </div>
          ) : null}
          {planMessage?.executionPlan ? (
            <section className="plan-dock" aria-label="当前任务计划">
              <TaskPlan
                key={`${conversationId}-${planMessage.id}`}
                plan={planMessage.executionPlan}
                active={currentGeneration?.assistantId === planMessage.id}
                disabled={isGenerating}
                onContinue={() => {
                  if (isGenerating) return;
                  if (pendingQuestion && pendingQuestion.requires_input !== false) {
                    showInterrupt(pendingQuestion);
                    return;
                  }
                  const plan = {
                    ...planMessage.executionPlan,
                    tasks: planMessage.executionPlan!.tasks.map((task) => ({
                      ...task,
                      result: task.result.slice(0, 250),
                    })),
                  };
                  void sendMessage(
                    `继续执行这份任务计划的剩余步骤，先恢复已完成结果，更新计划后继续。完整结果参考此前记录。计划：${JSON.stringify(plan)}`,
                    true,
                  );
                }}
              />
            </section>
          ) : null}
          {toolStatus ? (
            <div className="tool-status" role="status">
              <GlobalOutlined spin={isGenerating} />
              <span>{toolStatus}</span>
            </div>
          ) : null}
          <div className="starter-prompts">
            {starterPrompts.map((prompt) => (
              <button key={prompt} onClick={() => setDraft(prompt)}>
                {prompt}
              </button>
            ))}
          </div>
          <Dragger
            className="composer-dropzone"
            accept={attachmentAccept}
            multiple={false}
            showUploadList={false}
            openFileDialogOnClick={false}
            disabled={isGenerating || attachments.length >= 5}
            beforeUpload={(file) => {
              void uploadAttachment(file);
              return false;
            }}
          >
            <div className="composer">
              {attachments.length ? (
                <div className="composer-attachments" aria-label="待发送附件">
                  {attachments.map((attachment) => (
                    <div className="composer-attachment" key={attachment.id}>
                      <span className={`attachment-icon ${attachment.materialType}`}>
                        {attachmentIcons[attachment.materialType]}
                      </span>
                      <span title={attachment.title}>{attachment.title}</span>
                      <Button
                        type="default"
                        size="small"
                        icon={<DeleteOutlined />}
                        aria-label={`移除附件：${attachment.title}`}
                        onClick={() =>
                          setAttachments((items) =>
                            items.filter((item) => item.id !== attachment.id),
                          )
                        }
                      />
                    </div>
                  ))}
                </div>
              ) : null}
              <Input.TextArea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onPressEnter={(event) => {
                  if (!event.shiftKey) {
                    event.preventDefault();
                    void sendMessage();
                  }
                }}
                placeholder="描述你遇到的具体场景，也可以把文件拖到这里"
                autoSize={{ minRows: 2, maxRows: 5 }}
                aria-label="消息内容"
              />
              <div className="composer-footer">
                <div className="composer-actions-left">
                  <Tooltip title="开启后先拆解任务，再逐步执行；关闭时由助手判断是否需要计划">
                    <Button
                      type={usePlan ? 'primary' : 'text'}
                      size="small"
                      icon={<UnorderedListOutlined />}
                      aria-pressed={usePlan}
                      disabled={isGenerating}
                      onClick={() => setUsePlan((value) => !value)}
                    >
                      任务计划
                    </Button>
                  </Tooltip>
                  <Upload
                    accept={attachmentAccept}
                    multiple={false}
                    showUploadList={false}
                    beforeUpload={(file) => {
                      void uploadAttachment(file);
                      return false;
                    }}
                  >
                    <Tooltip title="添加图片、音频、文档或表格">
                      <Button
                        type="text"
                        size="small"
                        icon={<PaperClipOutlined />}
                        loading={isUploading}
                        disabled={isGenerating || attachments.length >= 5}
                      >
                        附件
                      </Button>
                    </Tooltip>
                  </Upload>
                  <span>可拖入图片、音频、文档、Excel/CSV，单个不超过 20 MB</span>
                </div>
                {isGenerating ? (
                  <Button danger icon={<StopOutlined />} onClick={stopGenerating}>
                    停止
                  </Button>
                ) : (
                  <Button
                    type="primary"
                    icon={<SendOutlined />}
                    onClick={() => void sendMessage()}
                    disabled={(!draft.trim() && !attachments.length) || isUploading}
                  >
                    发送
                  </Button>
                )}
              </div>
            </div>
          </Dragger>
          <Button
            className="plan-convert"
            type="text"
            icon={<ArrowRightOutlined />}
            onClick={() => {
              const latestAssistant = [...localMessages]
                .reverse()
                .find((item) => item.role === 'assistant' && item.content);
              const latestUser = [...localMessages]
                .reverse()
                .find((item) => item.role === 'user' && item.content);
              const userGoal = latestUser?.content.trim() ?? '';
              const suggestion = latestAssistant?.content
                ? `参考建议：${latestAssistant.content.trim()}`
                : '';
              const goal = [userGoal, suggestion].filter(Boolean).join('\n\n').slice(0, 500);
              navigate('/plans', { state: goal ? { goal } : undefined });
            }}
          >
            将这次建议转为行动计划
          </Button>
        </div>
      </main>
      <Modal
        open={Boolean(interruptDialog)}
        title={
          dialogCopy?.problems?.some((item) => item.includes('截断'))
            ? '方案还没有输出完整'
            : dialogCopy?.kind === 'error'
              ? '进度已保存，可继续处理'
              : '需要确认的问题'
        }
        centered
        styles={{ body: { maxHeight: '55vh', overflowY: 'auto' } }}
        onCancel={dismissQuestion}
        footer={[
          <Button key="later" onClick={dismissQuestion}>
            稍后处理
          </Button>,
          <Button
            key="cancel"
            danger
            disabled={isGenerating}
            onClick={() => submitQuestion('cancel')}
          >
            结束任务
          </Button>,
          <Button
            key="continue"
            type="primary"
            disabled={isGenerating || (!interruptOption && !interruptAnswer.trim())}
            onClick={() => submitQuestion('continue')}
          >
            提交并继续
          </Button>,
        ]}
      >
        <p>
          <strong>{dialogCopy?.question}</strong>
        </p>
        <p>{dialogCopy?.reason}</p>
        {dialogCopy?.problems?.length ? (
          <ul className="execution-interrupt-problems">
            {dialogCopy.problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        ) : null}
        {dialogCopy?.recommendation ? (
          <p className="execution-interrupt-recommendation">{dialogCopy.recommendation}</p>
        ) : null}
        <Space wrap className="execution-interrupt-options">
          {dialogCopy?.options.map((option) => (
            <Button
              key={option}
              type={interruptOption === option ? 'primary' : 'default'}
              onClick={() => setInterruptOption(option)}
              aria-pressed={interruptOption === option}
            >
              {option}
            </Button>
          ))}
        </Space>
        <Input.TextArea
          aria-label="补充说明或自定义回答"
          placeholder="有其他安排？可以在这里补充，也可以直接选择上方选项。"
          value={interruptAnswer}
          onChange={(event) => setInterruptAnswer(event.target.value)}
          autoSize={{ minRows: 3, maxRows: 7 }}
          maxLength={5000}
          style={{ marginTop: 16 }}
        />
      </Modal>
      <Modal
        title="重命名会话"
        open={Boolean(renamingConversation)}
        okText="保存"
        cancelText="取消"
        confirmLoading={updateConversation.isPending}
        onOk={() => void submitRename()}
        onCancel={() => setRenamingConversation(undefined)}
      >
        <Input
          value={renameDraft}
          maxLength={100}
          showCount
          autoFocus
          aria-label="会话名称"
          onChange={(event) => setRenameDraft(event.target.value)}
          onPressEnter={() => void submitRename()}
        />
      </Modal>
    </div>
  );
}
