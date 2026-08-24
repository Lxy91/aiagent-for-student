import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Card, Form, Input, Segmented, Typography } from 'antd';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { BrandMark } from '../../components/BrandMark';
import { apiClient } from '../../services/api-client';
import {
  clearStoredSession,
  getStoredSession,
  storeSession,
  type StoredSession,
} from '../../services/session';

interface AuthContextValue {
  session: StoredSession | null;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside AuthProvider');
  return value;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [session, setSession] = useState(getStoredSession);
  const logout = useCallback(() => {
    clearStoredSession();
    queryClient.clear();
    setSession(null);
  }, [queryClient]);
  const authenticate = useCallback(
    (next: StoredSession) => {
      queryClient.clear();
      storeSession(next);
      setSession(next);
    },
    [queryClient],
  );
  useEffect(() => {
    window.addEventListener('workplace-agent:unauthorized', logout);
    return () => window.removeEventListener('workplace-agent:unauthorized', logout);
  }, [logout]);
  const value = useMemo(() => ({ session, logout }), [session, logout]);

  if (!session) {
    return <AuthPage onAuthenticated={authenticate} />;
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

function AuthPage({ onAuthenticated }: { onAuthenticated: (session: StoredSession) => void }) {
  const [mode, setMode] = useState<'登录' | '注册'>('登录');
  const mutation = useMutation({
    mutationFn: async (values: { email: string; password: string; displayName?: string }) =>
      mode === '登录'
        ? apiClient.login(values)
        : apiClient.register({ ...values, displayName: values.displayName ?? '新用户' }),
    onSuccess: onAuthenticated,
  });
  return (
    <main className="auth-page">
      <Card className="auth-card">
        <div className="auth-brand">
          <BrandMark />
          <div>
            <strong>启程</strong>
            <span>职场适应智能体</span>
          </div>
        </div>
        <Typography.Title level={2}>
          {mode === '登录' ? '欢迎回来' : '创建你的账户'}
        </Typography.Title>
        <Typography.Paragraph type="secondary">
          登录后，对话、记忆和行动计划会保存到服务端。
        </Typography.Paragraph>
        <Segmented
          block
          value={mode}
          options={['登录', '注册']}
          onChange={(value) => setMode(value as '登录' | '注册')}
        />
        {mutation.error ? <Alert type="error" showIcon title={mutation.error.message} /> : null}
        <Form layout="vertical" onFinish={(values) => mutation.mutate(values)} requiredMark={false}>
          {mode === '注册' ? (
            <Form.Item
              label="昵称"
              name="displayName"
              rules={[{ required: true, message: '请输入昵称' }]}
            >
              <Input autoComplete="name" />
            </Form.Item>
          ) : null}
          <Form.Item
            label="邮箱"
            name="email"
            rules={[{ required: true, type: 'email', message: '请输入有效邮箱' }]}
          >
            <Input autoComplete="email" />
          </Form.Item>
          <Form.Item
            label="密码"
            name="password"
            rules={[{ required: true, min: 8, message: '密码至少 8 位' }]}
          >
            <Input.Password autoComplete={mode === '登录' ? 'current-password' : 'new-password'} />
          </Form.Item>
          <Button htmlType="submit" type="primary" block loading={mutation.isPending}>
            {mode}
          </Button>
        </Form>
      </Card>
    </main>
  );
}
