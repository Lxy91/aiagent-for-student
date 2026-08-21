import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './app/App';
import { AuthProvider } from './features/auth/AuthProvider';
import './styles/global.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#26695c',
          colorInfo: '#26695c',
          colorSuccess: '#3d7a57',
          colorWarning: '#b7792b',
          borderRadius: 12,
          borderRadiusLG: 18,
          colorText: '#1d2925',
          colorBgLayout: '#f3f4ee',
          fontFamily:
            "Inter, 'PingFang SC', 'Microsoft YaHei', system-ui, -apple-system, sans-serif",
        },
        components: {
          Button: { controlHeight: 40, fontWeight: 600 },
          Card: { paddingLG: 20 },
          Menu: { itemHeight: 46, itemBorderRadius: 12 },
        },
      }}
    >
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <BrowserRouter>
              <App />
            </BrowserRouter>
          </AuthProvider>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
