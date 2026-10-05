import type { ReactNode } from 'react';
import { Card, Empty, Skeleton } from 'antd';

interface StateCardProps {
  loading: boolean;
  empty?: boolean;
  emptyText?: string;
  emptyClassName?: string;
  children: ReactNode;
}

export function StateCard({
  loading,
  empty,
  emptyText = '暂无内容',
  emptyClassName,
  children,
}: StateCardProps) {
  if (loading) {
    return (
      <Card className="surface-card">
        <Skeleton active paragraph={{ rows: 5 }} />
      </Card>
    );
  }

  if (empty) {
    return (
      <Card className={`surface-card ${emptyClassName ?? ''}`.trim()}>
        <Empty description={emptyText} />
      </Card>
    );
  }

  return children;
}
