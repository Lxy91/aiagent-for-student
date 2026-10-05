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
  const [attachments, setAttachments] = useState<WorkMaterial[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [conversationId, setConversationId] = useState<string>();
  const [renamingConversation, setRenamingConversation] = useState<Conversation>();
  const [renameDraft, setRenameDraft] = useState('');
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

  const sendMessage = async (content = draft) => {
    const trimmedContent = content.trim();
    const queuedAttachments = attachments;
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
    setDraft('');
    setAttachments([]);
    const controller = new AbortController();
    generationControllersRef.current.set(targetId, controller);
    setGenerations((items) => ({ ...items, [targetId]: { assistantId } }));
    try {
      await apiClient.streamMessage(
        targetId,
        trimmedContent,
        queuedAttachments.map((item) => item.id),
        {
          onStarted: () => {
            void queryClient.invalidateQueries({ queryKey: ['conversations'] });
          },
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
        },
        controller.signal,
      );
      await queryClient.invalidateQueries({ queryKey: ['messages', targetId] });
    } catch (error) {
      if (!controller.signal.aborted) {
        message.error(error instanceof Error ? error.message : '消息发送失败');
        updateCachedMessages(targetId, (items) => items.filter((item) => item.id !== assistantId));
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
                    {item.content ? (
                      item.role === 'assistant' ? (
                        <AssistantMarkdown content={item.content} />
                      ) : (
                        item.content
                          .split('\n')
                          .map((paragraph, index) =>
                            paragraph ? (
                              <p key={`${item.id}-${index}`}>{paragraph}</p>
                            ) : (
                              <br key={index} />
                            ),
                          )
                      )
                    ) : item.role === 'assistant' ? (
                      <span className="typing-indicator">
                        <span />
                        <span />
                        <span />
                      </span>
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
                        type="text"
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
