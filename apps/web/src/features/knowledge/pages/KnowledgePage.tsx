import {
  CheckCircleFilled,
  ClockCircleOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  FileTextOutlined,
  MoreOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { App, Button, Card, Dropdown, Progress, Table, Tag, Upload } from 'antd';
import type { UploadProps } from 'antd';
import { PageHeader } from '../../../components/PageHeader';
import { apiClient } from '../../../services/api-client';
import type { KnowledgeDocument } from '../../../types/domain';

const { Dragger } = Upload;

const statusView = {
  ready: { color: 'success', icon: <CheckCircleFilled />, text: '可检索' },
  processing: { color: 'processing', icon: <ClockCircleOutlined />, text: '处理中' },
  failed: { color: 'error', icon: <ReloadOutlined />, text: '处理失败' },
} as const;

export function KnowledgePage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { data = [], isLoading } = useQuery({
    queryKey: ['documents'],
    queryFn: apiClient.getDocuments,
  });
  const upload = useMutation({
    mutationFn: apiClient.uploadDocument,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['documents'] });
      message.success('文档已进入处理队列');
    },
  });

  const uploadProps: UploadProps = {
    multiple: false,
    showUploadList: false,
    accept: '.pdf,.docx,.md,.txt',
    beforeUpload: (file) => {
      const validType = /\.(pdf|docx|md|txt)$/i.test(file.name);
      if (!validType) {
        message.error('仅支持 PDF、DOCX、Markdown 和 TXT');
        return Upload.LIST_IGNORE;
      }
      void upload.mutateAsync(file);
      return false;
    },
  };

  return (
    <div className="page-container knowledge-page">
      <PageHeader
        eyebrow="可信依据"
        title="知识库"
        description="管理可追溯的职场资料。回答只引用本次检索到并通过校验的片段。"
      />
      <div className="knowledge-stats">
        <Card>
          <FileTextOutlined />
          <div>
            <strong>{data.length}</strong>
            <span>份文档</span>
          </div>
        </Card>
        <Card>
          <SafetyCertificateOutlined />
          <div>
            <strong>
              {data.filter((item) => item.trustLevel === 'A' || item.trustLevel === 'B').length}
            </strong>
            <span>份高可信资料</span>
          </div>
        </Card>
        <Card>
          <CheckCircleFilled />
          <div>
            <strong>{data.reduce((total, item) => total + item.chunks, 0)}</strong>
            <span>个可检索片段</span>
          </div>
        </Card>
      </div>
      <Dragger {...uploadProps} className="knowledge-uploader" disabled={upload.isPending}>
        <p className="ant-upload-drag-icon">
          <CloudUploadOutlined />
        </p>
        <p className="ant-upload-text">拖入资料，或点击选择文件</p>
        <p className="ant-upload-hint">支持 PDF、DOCX、Markdown、TXT，单个文件不超过 20 MB</p>
        {upload.isPending ? <Progress percent={65} size="small" status="active" /> : null}
      </Dragger>
      <Card
        className="document-table surface-card"
        title="文档列表"
        extra={<span>{data.length} 份资料</span>}
      >
        <Table<KnowledgeDocument>
          rowKey="id"
          loading={isLoading}
          dataSource={data}
          pagination={false}
          scroll={{ x: 760 }}
          columns={[
            {
              title: '文档',
              dataIndex: 'title',
              key: 'title',
              render: (title: string, item) => (
                <div className="document-name">
                  <span>
                    <FileTextOutlined />
                  </span>
                  <div>
                    <strong>{title}</strong>
                    <small>{item.source}</small>
                  </div>
                </div>
              ),
            },
            {
              title: '可信等级',
              dataIndex: 'trustLevel',
              key: 'trustLevel',
              width: 110,
              render: (level: string) => (
                <Tag color={level === 'A' ? 'green' : level === 'B' ? 'blue' : 'default'}>
                  等级 {level}
                </Tag>
              ),
            },
            {
              title: '片段数',
              dataIndex: 'chunks',
              key: 'chunks',
              width: 90,
              render: (chunks: number) => chunks || '—',
            },
            {
              title: '状态',
              dataIndex: 'status',
              key: 'status',
              width: 120,
              render: (status: KnowledgeDocument['status']) => {
                const view = statusView[status];
                return (
                  <Tag color={view.color} icon={view.icon}>
                    {view.text}
                  </Tag>
                );
              },
            },
            { title: '更新时间', dataIndex: 'updatedAt', key: 'updatedAt', width: 130 },
            {
              title: '',
              key: 'action',
              width: 48,
              render: () => (
                <Dropdown
                  menu={{
                    items: [
                      { key: 'retry', icon: <ReloadOutlined />, label: '重新处理' },
                      { type: 'divider' },
                      { key: 'delete', danger: true, icon: <DeleteOutlined />, label: '删除' },
                    ],
                  }}
                >
                  <Button type="text" icon={<MoreOutlined />} aria-label="文档操作" />
                </Dropdown>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
