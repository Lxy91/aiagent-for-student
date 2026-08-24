import {
  ArrowRightOutlined,
  CheckCircleFilled,
  CopyOutlined,
  DislikeOutlined,
  LikeOutlined,
  GlobalOutlined,
  LinkOutlined,
  LoadingOutlined,
  PlusOutlined,
  SendOutlined,
  StopOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { App, Avatar, Button, Collapse, Input, Segmented, Space, Tag, Tooltip } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { BrandMark } from '../../../components/BrandMark';
import { StateCard } from '../../../components/StateCard';
import { apiClient } from '../../../services/api-client';
import type { ChatMessage, ReasoningStep } from '../../../types/domain';

const starterPrompts = ['怎么向领导澄清任务？', '帮我准备第一次周会', '把模糊目标拆成计划'];

interface ConversationGeneration {
  assistantId: string;
  toolStatus?: string;
}

function ExecutionTrace({ steps }: { steps: ReasoningStep[] }) {
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
              {steps.map((step) =>
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
                    {step.detail}
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

export function ChatPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState('');
  const [conversationId, setConversationId] = useState<string>();
  const [generations, setGenerations] = useState<Record<string, ConversationGeneration>>({});
  const generationControllersRef = useRef(new Map<string, AbortController>());
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
  const messages = useQuery({
    queryKey: ['messages', conversationId],
    queryFn: () => apiClient.getMessages(conversationId!),
    enabled: Boolean(conversationId),
    staleTime: Number.POSITIVE_INFINITY,
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

  const updateGenerationStatus = (
    targetId: string,
    assistantId: string,
    toolStatus: string,
  ) => {
    setGenerations((items) => {
      const current = items[targetId];
      if (current?.assistantId !== assistantId) return items;
      return { ...items, [targetId]: { ...current, toolStatus } };
    });
  };

  const sendMessage = async (content = draft) => {
    const trimmedContent = content.trim();
    if (!trimmedContent) return;
    const targetId = await ensureConversation();
    if (generationControllersRef.current.has(targetId)) return;
    await queryClient.cancelQueries({ queryKey: ['messages', targetId], exact: true });
    const now = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    const assistantId = `assistant-${Date.now()}`;
    updateCachedMessages(targetId, (items) => [
      ...items,
      { id: `user-${Date.now()}`, role: 'user', content: trimmedContent, createdAt: now },
      { id: assistantId, role: 'assistant', content: '', createdAt: now },
    ]);
    setDraft('');
    const controller = new AbortController();
    generationControllersRef.current.set(targetId, controller);
    setGenerations((items) => ({ ...items, [targetId]: { assistantId } }));
    try {
      await apiClient.streamMessage(
        targetId,
        trimmedContent,
        {
          onStarted: () => undefined,
          onDelta: (text) =>
            updateCachedMessages(targetId, (items) =>
              items.map((item) =>
                item.id === assistantId ? { ...item, content: item.content + text } : item,
              ),
            ),
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
          onCitations: (citations) =>
            updateCachedMessages(targetId, (items) =>
              items.map((item) => (item.id === assistantId ? { ...item, citations } : item)),
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
        },
        controller.signal,
      );
      await queryClient.invalidateQueries({ queryKey: ['messages', targetId] });
    } catch (error) {
      if (!controller.signal.aborted) {
        message.error(error instanceof Error ? error.message : '消息发送失败');
        updateCachedMessages(targetId, (items) =>
          items.filter((item) => item.id !== assistantId),
        );
      }
    } finally {
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

  const stopGenerating = () => {
    if (!conversationId) return;
    generationControllersRef.current.get(conversationId)?.abort();
    message.info('已停止生成');
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
        {conversations.data?.map((conversation) => (
          <button
            key={conversation.id}
            className={`conversation-item ${conversation.id === conversationId ? 'active' : ''}`}
            onClick={() => setConversationId(conversation.id)}
          >
            <span>{conversation.title}</span>
            <small>{new Date(conversation.created_at).toLocaleDateString('zh-CN')}</small>
          </button>
        ))}
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
            <span>V0.2 · 实时工具调用与来源追溯</span>
          </div>
          <Segmented options={['标准对话', '临时对话']} size="small" />
        </div>

        <StateCard
          loading={conversations.isLoading || messages.isLoading}
          empty={!localMessages.length}
          emptyText="开始第一次对话"
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
                    {item.content ? (
                      item.content
                        .split('\n')
                        .map((paragraph, index) =>
                          paragraph ? (
                            <p key={`${item.id}-${index}`}>{paragraph}</p>
                          ) : (
                            <br key={index} />
                          ),
                        )
                    ) : (
                      <span className="typing-indicator">
                        <span />
                        <span />
                        <span />
                      </span>
                    )}
                  </div>
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
                  {item.role === 'assistant' && item.content ? (
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
          <div className="composer">
            <Input.TextArea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onPressEnter={(event) => {
                if (!event.shiftKey) {
                  event.preventDefault();
                  void sendMessage();
                }
              }}
              placeholder="描述你遇到的具体场景，Shift + Enter 换行"
              autoSize={{ minRows: 2, maxRows: 5 }}
              aria-label="消息内容"
            />
            <div className="composer-footer">
              <span>AI 建议仅供参考，重要决定请结合实际情况判断。</span>
              {isGenerating ? (
                <Button danger icon={<StopOutlined />} onClick={stopGenerating}>
                  停止
                </Button>
              ) : (
                <Button
                  type="primary"
                  icon={<SendOutlined />}
                  onClick={() => void sendMessage()}
                  disabled={!draft.trim()}
                >
                  发送
                </Button>
              )}
            </div>
          </div>
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
    </div>
  );
}
