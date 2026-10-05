import {
  AimOutlined,
  BookOutlined,
  FileDoneOutlined,
  LinkOutlined,
  RiseOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { App, Button, Card, Col, Collapse, Empty, Row, Segmented, Space, Tag } from 'antd';
import dayjs from 'dayjs';
import { useState } from 'react';
import { PageHeader } from '../../../components/PageHeader';
import { StateCard } from '../../../components/StateCard';
import { apiClient } from '../../../services/api-client';

const sectionLabels: Record<string, string> = {
  completed: '本期完成',
  learnings: '经验沉淀',
  risks: '风险与确认',
  next_steps: '下一步',
};

export function GrowthPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [periodType, setPeriodType] = useState<'weekly' | 'monthly'>('weekly');
  const { data: profile, isLoading } = useQuery({
    queryKey: ['growth-profile'],
    queryFn: apiClient.getGrowthProfile,
  });
  const { data: reports = [] } = useQuery({
    queryKey: ['reports'],
    queryFn: apiClient.getReports,
  });
  const generate = useMutation({
    mutationFn: async () => {
      const end = dayjs();
      const start = periodType === 'weekly' ? end.subtract(6, 'day') : end.startOf('month');
      return apiClient.generateReport({
        periodType,
        periodStart: start.format('YYYY-MM-DD'),
        periodEnd: end.format('YYYY-MM-DD'),
      });
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['reports'] }),
        queryClient.invalidateQueries({ queryKey: ['growth-profile'] }),
      ]);
      message.success('已生成只引用可验证来源的草稿');
    },
  });

  return (
    <div className="page-container growth-page">
      <PageHeader
        eyebrow="V0.3 · 成长闭环"
        title="成长档案"
        description="把完成任务、反馈和工作材料沉淀成有来源的能力证据，并据此安排下一次刻意练习。"
        action={
          <Space>
            <Segmented
              value={periodType}
              options={[
                { label: '周报', value: 'weekly' },
                { label: '月报', value: 'monthly' },
              ]}
              onChange={(value) => setPeriodType(value as 'weekly' | 'monthly')}
            />
            <Button
              type="primary"
              icon={<FileDoneOutlined />}
              loading={generate.isPending}
              onClick={() => generate.mutate()}
            >
              生成草稿
            </Button>
          </Space>
        }
      />
      <StateCard loading={isLoading}>
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={10}>
            <Card className="surface-card growth-summary-card">
              <span className="growth-summary-icon">
                <RiseOutlined />
              </span>
              <strong>{profile?.evidence.length ?? 0}</strong>
              <span>条可追溯能力证据</span>
              <p>只展示能回到任务、反馈或材料来源的成长记录。</p>
            </Card>
          </Col>
          <Col xs={24} lg={14}>
            <Card className="surface-card" title="个性化学习路线" extra={<AimOutlined />}>
              <div className="learning-route">
                {(profile?.recommendations ?? []).map((item, index) => (
                  <div className="learning-route-item" key={item.capability}>
                    <div className="learning-step-index">{index + 1}</div>
                    <div className="learning-route-copy">
                      <div>
                        <Space>
                          <span>{item.capability}</span>
                          <Tag>{item.evidenceCount} 条证据</Tag>
                        </Space>
                      </div>
                      <p>{item.reason}</p>
                      <strong>{item.nextAction}</strong>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </Col>
        </Row>
        <div className="growth-grid">
          <Card className="surface-card" title="能力证据" extra={<BookOutlined />}>
            {profile?.evidence.length ? (
              <div className="evidence-list">
                {profile.evidence.map((item) => (
                  <div className="evidence-item" key={item.id}>
                    <div>
                      <Space wrap>
                        <Tag color="green">{item.capability}</Tag>
                        <span>{item.summary}</span>
                      </Space>
                    </div>
                    <small>
                      <LinkOutlined /> {item.sourceTitle} · {item.observedAt}
                    </small>
                  </div>
                ))}
              </div>
            ) : (
              <Empty description="完成任务或导入会议材料后，这里会出现第一条证据" />
            )}
          </Card>
          <Card className="surface-card" title="报告草稿" extra={`${reports.length} 份`}>
            {reports.length ? (
              <Collapse
                accordion
                items={reports.map((report) => ({
                  key: report.id,
                  label: (
                    <div className="report-title">
                      <strong>{report.title}</strong>
                      <span>{report.sources.length} 个来源</span>
                    </div>
                  ),
                  children: (
                    <Space direction="vertical" size={16} style={{ width: '100%' }}>
                      {Object.entries(report.sections).map(([key, items]) => (
                        <div className="report-section" key={key}>
                          <strong>{sectionLabels[key] ?? key}</strong>
                          <ul>
                            {items.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      ))}
                      <div className="report-sources">
                        <strong>事实来源</strong>
                        {report.sources.length ? (
                          report.sources.map((source) => (
                            <Tag key={`${source.type}-${source.id}`}>{source.title}</Tag>
                          ))
                        ) : (
                          <span>暂无可验证来源</span>
                        )}
                      </div>
                    </Space>
                  ),
                }))}
              />
            ) : (
              <Empty description="生成周报或月报草稿后在此查看" />
            )}
          </Card>
        </div>
      </StateCard>
    </div>
  );
}
