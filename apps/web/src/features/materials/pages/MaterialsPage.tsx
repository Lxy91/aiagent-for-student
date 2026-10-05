import {
  AudioOutlined,
  CheckCircleFilled,
  CloudUploadOutlined,
  DeleteOutlined,
  FileImageOutlined,
  FileTextOutlined,
  LockOutlined,
  QuestionCircleOutlined,
  TableOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  App,
  Button,
  Card,
  Collapse,
  Descriptions,
  Drawer,
  Empty,
  Popconfirm,
  Progress,
  Skeleton,
  Space,
  Tag,
  Upload,
} from 'antd';
import type { UploadProps } from 'antd';
import type { ReactNode } from 'react';
import { useState } from 'react';
import { PageHeader } from '../../../components/PageHeader';
import { apiClient } from '../../../services/api-client';
import type { MaterialType, WorkMaterial } from '../../../types/domain';

const { Dragger } = Upload;

const materialIcons: Record<MaterialType, ReactNode> = {
  audio: <AudioOutlined />,
  image: <FileImageOutlined />,
  document: <FileTextOutlined />,
  spreadsheet: <TableOutlined />,
  text: <FileTextOutlined />,
};

const statusView = {
  ready: { color: 'success', text: '已形成草稿' },
  needs_confirmation: { color: 'warning', text: '等待补充文字' },
  blocked: { color: 'error', text: '隐私复核' },
} as const;

export function MaterialsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<WorkMaterial>();
  const { data = [], isLoading } = useQuery({
    queryKey: ['materials'],
    queryFn: apiClient.getMaterials,
  });
  const upload = useMutation({
    mutationFn: (file: File) => apiClient.uploadMaterial(file, 'meeting'),
    onSuccess: async (material) => {
      await queryClient.invalidateQueries({ queryKey: ['materials'] });
      await queryClient.invalidateQueries({ queryKey: ['growth-profile'] });
      message.success(
        material.status === 'needs_confirmation'
          ? '材料已接收，请补充文字内容后确认'
          : '材料已脱敏并生成可追溯草稿',
      );
    },
  });
  const remove = useMutation({
    mutationFn: apiClient.deleteMaterial,
    onSuccess: async () => {
      setSelected(undefined);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['materials'] }),
        queryClient.invalidateQueries({ queryKey: ['growth-profile'] }),
        queryClient.invalidateQueries({ queryKey: ['reports'] }),
      ]);
      message.success('资料及其派生内容已删除');
    },
  });

  const uploadProps: UploadProps = {
    multiple: false,
    showUploadList: false,
    accept: '.mp3,.wav,.m4a,.png,.jpg,.jpeg,.pdf,.docx,.xlsx,.xls,.csv,.md,.txt',
    beforeUpload: (file) => {
      void upload.mutateAsync(file);
      return false;
    },
  };

  return (
    <div className="page-container materials-page">
      <PageHeader
        eyebrow="V0.3 · 工作资料"
        title="资料收件箱"
        description="集中接收会议录音、截图和文档。所有草稿都保留来源；未配置识别能力时不会猜测材料内容。"
      />
      <div className="material-privacy-banner">
        <LockOutlined />
        <div>
          <strong>先脱敏，再形成草稿</strong>
          <span>邮箱与手机号会自动遮盖；高风险身份或凭据字段将阻止自动处理。</span>
        </div>
      </div>
      <Dragger {...uploadProps} className="material-uploader" disabled={upload.isPending}>
        <p className="ant-upload-drag-icon">
          <CloudUploadOutlined />
        </p>
        <p className="ant-upload-text">拖入会议录音、截图或文档</p>
        <p className="ant-upload-hint">
          支持 MP3/WAV/M4A、PNG/JPG、PDF/DOCX、Excel/CSV、MD/TXT，单个不超过 20 MB
        </p>
        {upload.isPending ? <Progress percent={60} size="small" status="active" /> : null}
      </Dragger>
      <Card
        className="surface-card material-list-card"
        title="最近资料"
        extra={`${data.length} 份`}
      >
        {isLoading ? (
          <Skeleton active paragraph={{ rows: 3 }} />
        ) : data.length ? (
          <div className="material-list">
            {data.map((item) => {
              const view = statusView[item.status];
              return (
                <div className="material-row" key={item.id}>
                  <div className="material-meta">
                    <span className={`material-icon ${item.materialType}`}>
                      {materialIcons[item.materialType]}
                    </span>
                    <div>
                      <Space wrap>
                        <strong>{item.title}</strong>
                        <Tag color={view.color}>{view.text}</Tag>
                        {item.privacyStatus === 'redacted' ? <Tag color="blue">已脱敏</Tag> : null}
                      </Space>
                      <small>
                        {item.createdAt} · {(item.sizeBytes / 1024).toFixed(1)} KB
                      </small>
                    </div>
                  </div>
                  <Space>
                    <Button type="link" key="view" onClick={() => setSelected(item)}>
                      查看草稿
                    </Button>
                    <Popconfirm
                      key="delete"
                      title="删除资料及派生内容？"
                      description="相关纪要、成长证据和引用该资料的报告也会删除。"
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => remove.mutate(item.id)}
                    >
                      <Button type="text" danger icon={<DeleteOutlined />} aria-label="删除资料" />
                    </Popconfirm>
                  </Space>
                </div>
              );
            })}
          </div>
        ) : (
          <Empty description="还没有资料，先导入一份会议材料" />
        )}
      </Card>
      <Drawer
        size="large"
        title="会议材料草稿"
        open={Boolean(selected)}
        onClose={() => setSelected(undefined)}
      >
        {selected ? (
          <Space direction="vertical" size={20} style={{ width: '100%' }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="来源">{selected.title}</Descriptions.Item>
              <Descriptions.Item label="处理状态">
                <Tag color={statusView[selected.status].color}>
                  {statusView[selected.status].text}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="隐私状态">{selected.privacyStatus}</Descriptions.Item>
            </Descriptions>
            {selected.minutes ? (
              <>
                <Card size="small" title="纪要摘要">
                  {selected.minutes.summary}
                </Card>
                <Collapse
                  defaultActiveKey={['actions', 'facts']}
                  items={[
                    {
                      key: 'actions',
                      label: `行动项 ${selected.minutes.actionItems.length}`,
                      children: selected.minutes.actionItems.length ? (
                        <ul className="minutes-list">
                          {selected.minutes.actionItems.map((item) => (
                            <li key={item}>
                              <CheckCircleFilled /> {item}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description="未识别到明确行动项"
                        />
                      ),
                    },
                    {
                      key: 'facts',
                      label: `待确认事实 ${selected.minutes.pendingFacts.length}`,
                      children: (
                        <ul className="minutes-list pending">
                          {selected.minutes.pendingFacts.map((item) => (
                            <li key={item}>
                              <QuestionCircleOutlined /> {item}
                            </li>
                          ))}
                        </ul>
                      ),
                    },
                  ]}
                />
              </>
            ) : (
              <Empty description="该材料未生成纪要；隐私复核通过后才能继续处理" />
            )}
          </Space>
        ) : null}
      </Drawer>
    </div>
  );
}
