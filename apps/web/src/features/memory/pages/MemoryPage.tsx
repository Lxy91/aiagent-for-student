import {
  DeleteOutlined,
  EditOutlined,
  PauseCircleOutlined,
  PlusOutlined,
  PushpinFilled,
  SearchOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  App,
  Button,
  Card,
  Collapse,
  Form,
  Input,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Switch,
  Tag,
  Upload,
  Alert,
} from 'antd';
import { useMemo, useState } from 'react';
import { ResumeAttachmentPreview } from '../components/ResumeAttachmentPreview';
import { PageHeader } from '../../../components/PageHeader';
import { StateCard } from '../../../components/StateCard';
import { apiClient } from '../../../services/api-client';
import type { MemoryItem, MemoryType } from '../../../types/domain';

const typeLabels: Record<MemoryType, { label: string; color: string }> = {
  profile: { label: '个人画像', color: 'blue' },
  preference: { label: '回答偏好', color: 'purple' },
  goal: { label: '长期目标', color: 'green' },
  experience: { label: '关键经历', color: 'gold' },
};

export function MemoryPage() {
  const { message } = App.useApp();
  const [attachmentOpen, setAttachmentOpen] = useState(false);
  const [filter, setFilter] = useState('全部');
  const [search, setSearch] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm<{ type: MemoryType; content: string }>();
  const queryClient = useQueryClient();
  const { data = [], isLoading } = useQuery({
    queryKey: ['memories'],
    queryFn: apiClient.getMemories,
  });
  const resume = useQuery({ queryKey: ['resume'], queryFn: apiClient.getResume });
  const refreshResume = () => queryClient.invalidateQueries({ queryKey: ['resume'] });
  const uploadResume = useMutation({
    mutationFn: apiClient.uploadResume,
    onSuccess: async (result) => {
      await refreshResume();
      if (result.summary) message.success('简历已上传并生成基础摘要，请确认后开启使用');
      else message.warning('简历原文已保存，摘要生成失败，请重试生成');
    },
    onError: (error: Error) => message.error(error.message),
  });
  const regenerateSummary = useMutation({
    mutationFn: apiClient.regenerateResumeSummary,
    onSuccess: (result) => {
      queryClient.setQueryData(['resume'], result);
      if (result.summary) message.success('摘要已重新生成');
      else message.warning('暂未生成可靠摘要，原文已保留，请稍后重试');
    },
    onError: (error: Error) => message.error(error.message),
  });
  const toggleResume = useMutation({
    mutationFn: apiClient.setResumeActive,
    onSuccess: refreshResume,
    onError: (error: Error) => message.error(error.message),
  });
  const deleteResume = useMutation({
    mutationFn: apiClient.deleteResume,
    onSuccess: refreshResume,
    onError: (error: Error) => message.error(error.message),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['memories'] });
  const update = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<MemoryItem> }) =>
      apiClient.updateMemory(id, patch),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: apiClient.deleteMemory,
    onSuccess: async () => {
      await refresh();
      message.success('记忆已删除，后续回答不会再使用');
    },
  });
  const create = useMutation({
    mutationFn: apiClient.createMemory,
    onSuccess: async () => {
      await refresh();
      setCreateOpen(false);
      form.resetFields();
      message.success('记忆已保存');
    },
  });

  const filteredMemories = useMemo(
    () =>
      data.filter((item) => {
        const matchesFilter = filter === '全部' || typeLabels[item.type].label === filter;
        return matchesFilter && item.content.toLowerCase().includes(search.toLowerCase());
      }),
    [data, filter, search],
  );

  return (
    <div className="page-container memory-page">
      <PageHeader
        eyebrow="由你掌控"
        title="记忆中心"
        description="只有经你确认的信息才会用于个性化回答，你可以随时停用、修改或删除。"
        action={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            添加记忆
          </Button>
        }
      />
      <Card className="memory-summary surface-card">
        <div>
          <strong>{data.filter((item) => item.active).length}</strong>
          <span>条正在使用</span>
        </div>
        <div>
          <strong>{data.filter((item) => item.pinned).length}</strong>
          <span>条已置顶</span>
        </div>
        <div>
          <strong>建议后确认</strong>
          <span>当前保存模式</span>
        </div>
        <p>敏感信息不会被自动提取。临时对话也不会产生长期记忆。</p>
      </Card>
      <div className="filter-bar">
        <Segmented
          value={filter}
          onChange={(value) => setFilter(String(value))}
          options={['全部', '我的简历', '回答偏好']}
        />
        {filter !== '我的简历' && (
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            prefix={<SearchOutlined />}
            placeholder="搜索记忆"
            allowClear
          />
        )}
      </div>
      {filter === '我的简历' ? (
        <Card className="surface-card">
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <Alert
              type="info"
              showIcon
              message="上传后默认关闭。开启后，仅将基础信息摘要用于后续对话和新建面试；对话追问细节时再按需查阅原文。已开始的面试需重新创建才能应用变更。替换简历后需重新开启。"
            />
            <Upload
              accept=".pdf,.docx,.txt,.md"
              showUploadList={false}
              disabled={
                uploadResume.isPending ||
                toggleResume.isPending ||
                deleteResume.isPending ||
                regenerateSummary.isPending
              }
              beforeUpload={(file) => {
                if (file.size > 20 * 1024 * 1024) {
                  message.error('简历文件不能超过 20 MB');
                  return false;
                }
                uploadResume.mutate(file);
                return false;
              }}
            >
              <Button icon={<PlusOutlined />} loading={uploadResume.isPending}>
                {resume.data ? '替换简历' : '上传我的简历'}
              </Button>
            </Upload>
            <span>支持 PDF、DOCX、TXT、Markdown，最大 20 MB；点击文件名可预览或下载原附件。</span>
            <StateCard
              loading={resume.isLoading}
              empty={!resume.data && !resume.isError}
              emptyText="还没有上传简历"
            >
              {resume.isError ? (
                <Alert
                  type="error"
                  message="简历加载失败"
                  description={resume.error instanceof Error ? resume.error.message : undefined}
                  action={<Button onClick={() => resume.refetch()}>重试</Button>}
                />
              ) : null}
              {resume.data ? (
                <>
                  <Space wrap>
                    <Button
                      type="link"
                      className="resume-attachment-link"
                      onClick={() => setAttachmentOpen(true)}
                    >
                      {resume.data.filename}
                    </Button>
                    <Switch
                      checked={resume.data.active}
                      loading={toggleResume.isPending}
                      disabled={
                        uploadResume.isPending ||
                        deleteResume.isPending ||
                        regenerateSummary.isPending ||
                        (!resume.data.summary && !resume.data.active)
                      }
                      onChange={(active) => toggleResume.mutate(active)}
                      checkedChildren="已开启"
                      unCheckedChildren="已关闭"
                      aria-label="将简历用于对话和面试"
                    />
                    <Popconfirm
                      title="删除简历？"
                      description="删除后将停止在后续对话和新面试中注入。"
                      onConfirm={() => deleteResume.mutate()}
                    >
                      <Button
                        danger
                        icon={<DeleteOutlined />}
                        loading={deleteResume.isPending}
                        disabled={
                          uploadResume.isPending ||
                          toggleResume.isPending ||
                          regenerateSummary.isPending
                        }
                      >
                        删除
                      </Button>
                    </Popconfirm>
                  </Space>
                  <p>更新于 {new Date(resume.data.updated_at).toLocaleString('zh-CN')}</p>
                  <div
                    style={{
                      whiteSpace: 'pre-wrap',
                      overflowWrap: 'anywhere',
                      maxHeight: 480,
                      overflowY: 'auto',
                    }}
                  >
                    <strong>基础信息摘要</strong>
                    {resume.data.summary ? (
                      <p>{resume.data.summary}</p>
                    ) : (
                      <Alert
                        type="warning"
                        showIcon
                        message="暂未生成可靠摘要，原文已保存"
                        description={
                          resume.data.summary_error ||
                          '请点击重新生成；生成前不会向对话或面试注入摘要。'
                        }
                      />
                    )}
                    <Button
                      onClick={() => regenerateSummary.mutate()}
                      loading={regenerateSummary.isPending}
                      disabled={
                        uploadResume.isPending || deleteResume.isPending || toggleResume.isPending
                      }
                    >
                      重新生成摘要
                    </Button>
                  </div>
                  <Collapse
                    items={[
                      {
                        key: 'source',
                        label: '查看提取文字',
                        children: (
                          <div
                            style={{
                              whiteSpace: 'pre-wrap',
                              overflowWrap: 'anywhere',
                              maxHeight: 480,
                              overflowY: 'auto',
                            }}
                          >
                            {resume.data.content}
                          </div>
                        ),
                      },
                    ]}
                  />
                </>
              ) : null}
            </StateCard>
          </Space>
        </Card>
      ) : (
        <StateCard
          loading={isLoading}
          empty={!filteredMemories.length}
          emptyText="没有符合条件的记忆"
        >
          <div className="memory-grid">
            {filteredMemories.map((item) => (
              <Card key={item.id} className={`memory-card ${!item.active ? 'inactive' : ''}`}>
                <div className="memory-card-top">
                  <Space>
                    <Tag color={typeLabels[item.type].color}>{typeLabels[item.type].label}</Tag>
                    {item.pinned ? <PushpinFilled className="pin-icon" /> : null}
                    {!item.active ? <Tag icon={<PauseCircleOutlined />}>已停用</Tag> : null}
                  </Space>
                  <Switch
                    size="small"
                    checked={item.active}
                    onChange={(active) => update.mutate({ id: item.id, patch: { active } })}
                    aria-label={item.active ? '停用记忆' : '启用记忆'}
                  />
                </div>
                <p>{item.content}</p>
                <div className="memory-source">
                  <span>{item.source}</span>
                  <span>{item.updatedAt}</span>
                </div>
                <div className="memory-actions">
                  <Button
                    type="text"
                    size="small"
                    icon={<PushpinFilled />}
                    onClick={() => update.mutate({ id: item.id, patch: { pinned: !item.pinned } })}
                  >
                    {item.pinned ? '取消置顶' : '置顶'}
                  </Button>
                  <Button type="text" size="small" icon={<EditOutlined />}>
                    编辑
                  </Button>
                  <Popconfirm
                    title="删除这条记忆？"
                    description="删除后会立即停止用于后续回答。"
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    onConfirm={() => remove.mutate(item.id)}
                  >
                    <Button danger type="text" size="small" icon={<DeleteOutlined />}>
                      删除
                    </Button>
                  </Popconfirm>
                </div>
              </Card>
            ))}
          </div>
        </StateCard>
      )}
      {attachmentOpen && resume.data ? (
        <ResumeAttachmentPreview
          filename={resume.data.filename}
          hasAttachment={resume.data.has_attachment}
          onClose={() => setAttachmentOpen(false)}
        />
      ) : null}
      <Modal
        title="添加记忆"
        open={createOpen}
        okText="保存"
        cancelText="取消"
        confirmLoading={create.isPending}
        onCancel={() => setCreateOpen(false)}
        onOk={() => form.submit()}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ type: 'preference' }}
          onFinish={(values) => create.mutate(values)}
        >
          <Form.Item name="type" label="记忆类型" rules={[{ required: true }]}>
            <Select
              options={Object.entries(typeLabels).map(([value, item]) => ({
                value,
                label: item.label,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="content"
            label="记内容"
            rules={[{ required: true, message: '请输入需要记住的内容' }]}
          >
            <Input.TextArea autoSize={{ minRows: 3, maxRows: 6 }} maxLength={500} showCount />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
