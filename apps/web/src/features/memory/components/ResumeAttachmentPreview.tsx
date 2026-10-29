import { DownloadOutlined } from '@ant-design/icons';
import { Alert, Button, Modal, Skeleton, Space } from 'antd';
import { useEffect, useState } from 'react';
import { apiClient } from '../../../services/api-client';

interface Attachment {
  blob: Blob;
  url: string;
  text?: string;
}

function WordPreview({ blob }: { blob: Blob }) {
  const [html, setHtml] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    let cancelled = false;
    const container = document.createElement('div');
    void import('docx-preview')
      .then(async ({ renderAsync }) => {
        await renderAsync(blob, container, undefined, {
          useBase64URL: true,
          renderAltChunks: false,
          renderComments: false,
        });
        if (!cancelled)
          setHtml(
            `<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0;background:#eee}</style></head><body>${container.innerHTML}</body></html>`,
          );
      })
      .catch(() => {
        if (!cancelled) setError('文档预览失败，可以下载原附件查看。');
      });
    return () => {
      cancelled = true;
      container.replaceChildren();
    };
  }, [blob]);
  if (error) return <Alert type="warning" showIcon message={error} />;
  if (!html) return <Skeleton active />;
  return (
    <iframe
      title="Word 简历附件预览"
      sandbox=""
      srcDoc={html}
      className="resume-attachment-frame"
    />
  );
}

export function ResumeAttachmentPreview({
  filename,
  hasAttachment,
  onClose,
}: {
  filename: string;
  hasAttachment: boolean;
  onClose: () => void;
}) {
  const [attachment, setAttachment] = useState<Attachment>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(hasAttachment);
  const extension = filename.split('.').pop()?.toLowerCase();
  useEffect(() => {
    if (!hasAttachment) return;
    const controller = new AbortController();
    let url: string | undefined;
    void apiClient
      .getResumeAttachment(controller.signal)
      .then(async (blob) => {
        const text = extension === 'txt' || extension === 'md' ? await blob.text() : undefined;
        if (controller.signal.aborted) return;
        url = URL.createObjectURL(blob);
        setAttachment({ blob, url, text });
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : '附件加载失败，请关闭后重试');
        setLoading(false);
      });
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [extension, hasAttachment]);

  return (
    <Modal
      open
      title={filename}
      onCancel={onClose}
      width="min(1100px, 96vw)"
      footer={
        <Space>
          {attachment && (
            <Button icon={<DownloadOutlined />} href={attachment.url} download={filename}>
              下载原附件
            </Button>
          )}
          <Button onClick={onClose}>关闭</Button>
        </Space>
      }
    >
      {!hasAttachment ? (
        <Alert
          type="info"
          showIcon
          message="这份简历上传时未保留原附件"
          description="请关闭弹窗，点击替换简历重新上传一次，即可查看和下载原附件。已提取的文字与摘要仍然保留。"
        />
      ) : null}
      {loading ? <Skeleton active paragraph={{ rows: 8 }} /> : null}
      {error ? <Alert type="error" showIcon message={error} /> : null}
      {attachment && extension === 'pdf' ? (
        <iframe title="PDF 简历附件预览" src={attachment.url} className="resume-attachment-frame" />
      ) : null}
      {attachment && extension === 'docx' ? <WordPreview blob={attachment.blob} /> : null}
      {attachment?.text !== undefined ? (
        <pre className="resume-attachment-text">{attachment.text}</pre>
      ) : null}
    </Modal>
  );
}
