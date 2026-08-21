import {
  BellOutlined,
  LockOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { Alert, Avatar, Button, Card, Form, Input, Select, Space, Switch } from 'antd';
import { PageHeader } from '../components/PageHeader';

export function SettingsPage() {
  return (
    <div className="page-container settings-page">
      <PageHeader
        eyebrow="偏好与隐私"
        title="设置"
        description="管理个人资料、回答偏好与长期记忆授权。"
      />
      <div className="settings-grid">
        <Card className="settings-nav surface-card">
          <button className="active">
            <UserOutlined /> 个人资料
          </button>
          <button>
            <SafetyCertificateOutlined /> AI 与记忆
          </button>
          <button>
            <BellOutlined /> 通知偏好
          </button>
          <button>
            <LockOutlined /> 隐私与数据
          </button>
        </Card>
        <div className="settings-content">
          <Card className="surface-card" title="个人资料">
            <div className="profile-row">
              <Avatar size={64}>林</Avatar>
              <div>
                <strong>林晓宇</strong>
                <span>这些信息有助于建议贴近你的当前阶段</span>
              </div>
              <Button>更换头像</Button>
            </div>
            <Form
              layout="vertical"
              initialValues={{
                stage: '大三 / 在岗实习',
                role: '产品经理',
                concern: '需求分析与沟通',
              }}
            >
              <div className="form-grid">
                <Form.Item label="当前阶段" name="stage">
                  <Select
                    options={[
                      { value: '大三 / 在岗实习', label: '大三 / 在岗实习' },
                      { value: '应届毕业生', label: '应届毕业生' },
                    ]}
                  />
                </Form.Item>
                <Form.Item label="目标岗位" name="role">
                  <Input />
                </Form.Item>
              </div>
              <Form.Item label="当前最想改善的能力" name="concern">
                <Input />
              </Form.Item>
              <Button type="primary">保存资料</Button>
            </Form>
          </Card>
          <Card className="surface-card" title="AI 与长期记忆">
            <div className="setting-row">
              <div>
                <strong>候选记忆建议</strong>
                <span>对稳定且未来有用的信息提出保存建议</span>
              </div>
              <Switch defaultChecked />
            </div>
            <div className="setting-row">
              <div>
                <strong>保存前确认</strong>
                <span>每条候选记忆都必须经过你确认</span>
              </div>
              <Switch defaultChecked disabled />
            </div>
            <div className="setting-row">
              <div>
                <strong>回答详细程度</strong>
                <span>控制默认回答长度，可在对话中临时调整</span>
              </div>
              <Select
                defaultValue="balanced"
                options={[
                  { value: 'brief', label: '简洁' },
                  { value: 'balanced', label: '适中' },
                  { value: 'detailed', label: '详细' },
                ]}
              />
            </div>
            <Alert type="info" showIcon title="临时对话不会写入长期记忆，也不会用于历史个性化。" />
          </Card>
          <Card className="surface-card danger-card" title="数据管理">
            <Space direction="vertical" size={12}>
              <span>你可以导出或删除账户数据。删除操作需要二次确认。</span>
              <Space>
                <Button>导出我的数据</Button>
                <Button danger>删除账户与数据</Button>
              </Space>
            </Space>
          </Card>
        </div>
      </div>
    </div>
  );
}
