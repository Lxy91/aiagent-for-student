import {
  ArrowRightOutlined,
  CheckCircleFilled,
  CopyOutlined,
  DislikeOutlined,
  LikeOutlined,
  PlusOutlined,
  SendOutlined,
  StopOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { App, Avatar, Button, Input, Segmented, Space, Tooltip } from 'antd';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { BrandMark } from '../../../components/BrandMark';
import { StateCard } from '../../../components/StateCard';
import { apiClient } from '../../../services/api-client';
import type { ChatMessage } from '../../../types/domain';

const starterPrompts = ['怎么向领导澄清任务？', '帮我准备第一次周会', '把模糊目标拆成计划'];

export function ChatPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState('');
  const [conversationId, setConversationId] = useState<string>();
  const [localMessages, setLocalMessages] = useState<ChatMessage[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const conversations = useQuery({
    queryKey: ['conversations'],
    queryFn: apiClient.getConversations,
  });
  const createConversation = useMutation({
    mutationFn: () => apiClient.createConversation(),
    onSuccess: async (conversation) => {
      setConversationId(conversation.id);
      setLocalMessages([]);
      await queryClient.invalidateQueries({ queryKey: ['conversations'] });
    },
  });
  const messages = useQuery({
    queryKey: ['messages', conversationId],
    queryFn: () => apiClient.getMessages(conversationId!),
    enabled: Boolean(conversationId),
  });

  useEffect(() => {
    if (!conversationId && conversations.data?.length) {
      setConversationId(conversations.data[0].id);
    }
  }, [conversationId, conversations.data]);

  useEffect(() => {
    if (messages.data) setLocalMessages(messages.data);
  }, [messages.data]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const selectedConversation = useMemo(
    () => conversations.data?.find((item) => item.id === conversationId),
    [conversationId, conversations.data],
  );

  const ensureConversation = async () => {
    if (conversationId) return conversationId;
    const conversation = await apiClient.createConversation();
    setConversationId(conversation.id);
    await queryClient.invalidateQueries({ queryKey: ['conversations'] });
    return conversation.id;
  };

  const sendMessage = async (content = draft) => {
    const trimmedContent = content.trim();
    if (!trimmedContent || isGenerating) return;
    const targetId = await ensureConversation();
    const now = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    const assistantId = `assistant-${Date.now()}`;
    setLocalMessages((items) => [
      ...items,
      { id: `user-${Date.now()}`, role: 'user', content: trimmedContent, createdAt: now },
      { id: assistantId, role: 'assistant', content: '', createdAt: now },
    ]);
    setDraft('');
    setIsGenerating(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await apiClient.streamMessage(
        targetId,
        trimmedContent,
        {
          onStarted: () => undefined,
          onDelta: (text) =>
            setLocalMessages((items) =>
              items.map((item) =>
                item.id === assistantId ? { ...item, content: item.content + text } : item,
              ),
            ),
        },
        controller.signal,
      );
      await queryClient.invalidateQueries({ queryKey: ['messages', targetId] });
    } catch (error) {
      if (!controller.signal.aborted) {
        message.error(error instanceof Error ? error.message : '消息发送失败');
        setLocalMessages((items) => items.filter((item) => item.id !== assistantId));
      }
    } finally {
      setIsGenerating(false);
      abortRef.current = null;
    }
  };

  const stopGenerating = () => {
    abortRef.current?.abort();
    setIsGenerating(false);
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
            <span>真实 API 已连接 · 消息流式返回</span>
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
            onClick={() => navigate('/plans')}
          >
            将这次建议转为行动计划
          </Button>
        </div>
      </main>
    </div>
  );
}
