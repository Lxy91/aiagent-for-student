import type { ReactNode } from 'react';
import { Card, Empty, Skeleton } from 'antd';

interface StateCardProps {
  loading: boolean;
  empty?: boolean;
  emptyText?: string;
  children: ReactNode;
}

export function StateCard({ loading, empty, emptyText = '暂无内容', children }: StateCardProps) {
  if (loading) {
    return (
      <Card className="surface-card">
        <Skeleton active paragraph={{ rows: 5 }} />
      </Card>
    );
  }

  if (empty) {
    return (
      <Card className="surface-card">
        <Empty description={emptyText} />
      </Card>
    );
  }

  return children;
}
