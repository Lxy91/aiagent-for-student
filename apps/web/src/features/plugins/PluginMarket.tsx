import { AppstoreOutlined, DownloadOutlined } from '@ant-design/icons';
import { Button, Card, Drawer, Empty, Space, Steps, Tag, Typography } from 'antd';
import { useState } from 'react';

// The host owns only this catalogue. Plugin runtime and personal data remain outside it.
const plugins = [
  {
    id: 'application-assistant',
    name: '投递填表助手',
    version: '0.5.0',
    description:
      '生成可编辑 Excel 资料表，补充期望薪资等信息后导入，由 AI 匹配企业投递表单。可独立使用，也可从记忆中心一键生成。',
    download: '/plugins/application-assistant.zip?v=0.5.0',
  },
];

export function PluginMarket() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        type="text"
        icon={<AppstoreOutlined />}
        aria-label="应用市场"
        onClick={() => setOpen(true)}
      >
        应用
      </Button>
      <Drawer title="应用市场" open={open} onClose={() => setOpen(false)} size={520}>
        <Typography.Paragraph type="secondary">
          按需扩展你的工作方式。插件独立安装和运行。
        </Typography.Paragraph>
        {plugins.map((plugin) => (
          <Card key={plugin.id} title={plugin.name} extra={<Tag>浏览器扩展</Tag>}>
            <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
              <Typography.Text>{plugin.description}</Typography.Text>
              <Typography.Text type="secondary">
                Chrome / Edge · v{plugin.version} · 本地安装版
              </Typography.Text>
              <Button
                type="primary"
                icon={<DownloadOutlined />}
                href={plugin.download}
                download={`启程投递填表助手-v${plugin.version}.zip`}
              >
                下载安装包
              </Button>
              <Steps
                orientation="vertical"
                size="small"
                items={[
                  { title: '解压安装包', description: '将 ZIP 解压到固定文件夹，保留该目录。' },
                  {
                    title: '在浏览器加载',
                    description:
                      '打开 chrome://extensions 或 edge://extensions，开启开发者模式，选择“加载已解压的扩展程序”。',
                  },
                  {
                    title: '打开插件开始使用',
                    description:
                      '在浏览器工具栏固定插件。导入简历或直接填写资料，打开企业投递页后识别并确认填入。',
                  },
                ]}
              />
              <Typography.Text type="secondary">
                基础填表可直接使用；自动生成资料通过插件本地服务读取 .env
                配置。复杂自定义控件和多段经历请在页面核对。
              </Typography.Text>
            </Space>
          </Card>
        ))}
        <div style={{ marginTop: 24 }}>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="更多插件，陆续加入" />
        </div>
      </Drawer>
    </>
  );
}
