import {
  BookOutlined,
  BulbOutlined,
  CalendarOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MessageOutlined,
  MoonOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { Avatar, Button, Dropdown, Layout, Menu, Space, Tooltip } from 'antd';
import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { Navigate, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { BrandMark } from '../components/BrandMark';
import { StateCard } from '../components/StateCard';
import { useAuth } from '../features/auth/AuthProvider';

const ChatPage = lazy(() =>
  import('../features/chat/pages/ChatPage').then((module) => ({ default: module.ChatPage })),
);
const KnowledgePage = lazy(() =>
  import('../features/knowledge/pages/KnowledgePage').then((module) => ({
    default: module.KnowledgePage,
  })),
);
const MemoryPage = lazy(() =>
  import('../features/memory/pages/MemoryPage').then((module) => ({ default: module.MemoryPage })),
);
const PlansPage = lazy(() =>
  import('../features/plans/pages/PlansPage').then((module) => ({ default: module.PlansPage })),
);
const SettingsPage = lazy(() =>
  import('../pages/SettingsPage').then((module) => ({ default: module.SettingsPage })),
);

const { Header, Sider, Content } = Layout;

const navigationItems = [
  { key: '/chat', icon: <MessageOutlined />, label: '智能对话' },
  { key: '/plans', icon: <CalendarOutlined />, label: '行动计划' },
  { key: '/memory', icon: <BulbOutlined />, label: '记忆中心' },
  { key: '/knowledge', icon: <BookOutlined />, label: '知识库' },
  { type: 'divider' as const },
  { key: '/settings', icon: <SettingOutlined />, label: '设置' },
];

function AppShell() {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { session, logout } = useAuth();
  const user = session!.user;

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  const selectedKey = useMemo(
    () => navigationItems.find((item) => item.key === location.pathname)?.key ?? '/chat',
    [location.pathname],
  );

  return (
    <Layout className="app-shell">
      <Sider
        className={`app-sider ${mobileOpen ? 'mobile-open' : ''}`}
        width={248}
        collapsedWidth={84}
        collapsed={collapsed}
        trigger={null}
        theme="light"
      >
        <div className="brand-lockup">
          <BrandMark />
          {!collapsed ? (
            <div>
              <strong>启程</strong>
              <span>职场适应智能体</span>
            </div>
          ) : null}
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={navigationItems}
          onClick={({ key }) => navigate(key)}
        />
        <div className="sider-footer">
          <Button
            type="text"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed((value) => !value)}
            aria-label={collapsed ? '展开侧边栏' : '收起侧边栏'}
          >
            {!collapsed ? '收起导航' : null}
          </Button>
        </div>
      </Sider>
      {mobileOpen ? (
        <button
          className="mobile-mask"
          aria-label="关闭导航"
          onClick={() => setMobileOpen(false)}
        />
      ) : null}
      <Layout>
        <Header className="app-header">
          <Button
            className="mobile-menu-button"
            type="text"
            icon={<MenuUnfoldOutlined />}
            onClick={() => setMobileOpen(true)}
            aria-label="打开导航"
          />
          <div className="header-context">
            <span className="status-dot" />
            <span>服务已连接</span>
            <span className="trace-label">V0.1 · FastAPI</span>
          </div>
          <Space size={8}>
            <Tooltip title="深色模式将在后续版本开放">
              <Button type="text" icon={<MoonOutlined />} aria-label="深色模式" />
            </Tooltip>
            <Dropdown menu={{ items: [{ key: 'logout', label: '退出登录' }], onClick: logout }}>
              <button className="user-chip" type="button">
                <Avatar size={34} icon={<UserOutlined />} />
                <div>
                  <strong>{user.displayName}</strong>
                  <span>{user.email}</span>
                </div>
              </button>
            </Dropdown>
          </Space>
        </Header>
        <Content className="app-content">
          <Suspense
            fallback={
              <div className="route-loading">
                <StateCard loading>{null}</StateCard>
              </div>
            }
          >
            <Outlet />
          </Suspense>
        </Content>
      </Layout>
    </Layout>
  );
}

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/chat" replace />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="plans" element={<PlansPage />} />
        <Route path="memory" element={<MemoryPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Route>
    </Routes>
  );
}
