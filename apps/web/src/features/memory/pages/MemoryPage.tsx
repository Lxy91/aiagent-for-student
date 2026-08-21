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
  Form,
  Input,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Switch,
  Tag,
} from 'antd';
import { useMemo, useState } from 'react';
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
  const [filter, setFilter] = useState('全部');
  const [search, setSearch] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm<{ type: MemoryType; content: string }>();
  const queryClient = useQueryClient();
  const { data = [], isLoading } = useQuery({
    queryKey: ['memories'],
    queryFn: apiClient.getMemories,
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
          options={['全部', '个人画像', '回答偏好', '长期目标', '关键经历']}
        />
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          prefix={<SearchOutlined />}
          placeholder="搜索记忆"
          allowClear
        />
      </div>
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
