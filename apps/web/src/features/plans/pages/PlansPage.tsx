import {
  CalendarOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  MoreOutlined,
  PlusOutlined,
  ThunderboltFilled,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  App,
  Button,
  Card,
  DatePicker,
  Dropdown,
  Form,
  Input,
  Modal,
  Progress,
  Segmented,
  Space,
  Tag,
} from 'antd';
import type { Dayjs } from 'dayjs';
import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { PageHeader } from '../../../components/PageHeader';
import { StateCard } from '../../../components/StateCard';
import { apiClient } from '../../../services/api-client';
import type { PlanTask, TaskStatus } from '../../../types/domain';

const columns: Array<{ key: TaskStatus; label: string; tone: string }> = [
  { key: 'todo', label: '待开始', tone: 'slate' },
  { key: 'doing', label: '进行中', tone: 'amber' },
  { key: 'done', label: '已完成', tone: 'green' },
];

const priorityMap = { high: '高优先级', medium: '中优先级', low: '低优先级' };

function TaskCard({
  task,
  onStatusChange,
}: {
  task: PlanTask;
  onStatusChange: (status: TaskStatus) => void;
}) {
  return (
    <Card className="task-card" size="small">
      <div className="task-card-top">
        <Tag variant="filled" color={task.priority === 'high' ? 'red' : 'default'}>
          {priorityMap[task.priority]}
        </Tag>
        <Dropdown
          menu={{
            items: columns.map((column) => ({ key: column.key, label: `移至${column.label}` })),
            onClick: ({ key }) => onStatusChange(key as TaskStatus),
          }}
        >
          <Button type="text" size="small" icon={<MoreOutlined />} aria-label="任务操作" />
        </Dropdown>
      </div>
      <h3>{task.title}</h3>
      <p>{task.description}</p>
      <div className="task-definition">
        <CheckCircleFilled />
        <span>{task.doneDefinition}</span>
      </div>
      <div className="task-meta">
        <span>
          <CalendarOutlined /> {task.dueAt.slice(5).replace('-', ' 月 ')} 日
        </span>
        <span>
          <ClockCircleOutlined /> {task.estimatedMinutes} 分钟
        </span>
      </div>
    </Card>
  );
}

export function PlansPage() {
  const { message } = App.useApp();
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm<{ goal: string; deadline?: Dayjs }>();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['plans'], queryFn: apiClient.getPlans });
  const updateTask = useMutation({
    mutationFn: ({ taskId, status }: { taskId: string; status: TaskStatus }) =>
      apiClient.updateTask(taskId, status),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['plans'] });
      message.success('任务状态已更新');
    },
  });
  const createPlan = useMutation({
    mutationFn: ({ goal, deadline }: { goal: string; deadline?: Dayjs }) =>
      apiClient.createPlan({ goal, deadline: deadline?.format('YYYY-MM-DD') }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['plans'] });
      setCreateOpen(false);
      form.resetFields();
      message.success('计划已创建');
    },
  });
  const plan = data?.[0];
  const completedCount = plan?.tasks.filter((task) => task.status === 'done').length ?? 0;
  const progress = plan ? Math.round((completedCount / plan.tasks.length) * 100) : 0;

  useEffect(() => {
    const state = location.state as { goal?: string } | null;
    if (!state?.goal) return;
    form.setFieldValue('goal', state.goal);
    setCreateOpen(true);
    navigate(location.pathname, { replace: true, state: null });
  }, [form, location.pathname, location.state, navigate]);

  return (
    <div className="page-container plans-page">
      <PageHeader
        eyebrow="行动闭环"
        title="行动计划"
        description="把模糊目标变成有完成定义、期限和优先级的下一步。"
        action={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            创建计划
          </Button>
        }
      />
      <StateCard loading={isLoading} empty={!plan} emptyText="还没有行动计划">
        {plan ? (
          <>
            <Card className="plan-overview surface-card">
              <div className="plan-overview-main">
                <div className="plan-icon">
                  <ThunderboltFilled />
                </div>
                <div>
                  <Space wrap>
                    <Tag color="green">进行中</Tag>
                    <span className="plan-deadline">
                      <CalendarOutlined /> 截止 {plan.deadline}
                    </span>
                  </Space>
                  <h2>{plan.title}</h2>
                  <p>{plan.goal}</p>
                </div>
              </div>
              <div className="plan-progress">
                <Progress type="circle" percent={progress} size={84} strokeColor="#26695c" />
                <span>
                  {completedCount}/{plan.tasks.length} 项完成
                </span>
              </div>
            </Card>

            <div className="board-toolbar">
              <Segmented options={['看板', '清单']} defaultValue="看板" />
              <span>任务更改会自动记录到计划版本中</span>
            </div>

            <div className="task-board">
              {columns.map((column) => {
                const tasks = plan.tasks.filter((task) => task.status === column.key);
                return (
                  <section key={column.key} className="task-column">
                    <div className="task-column-title">
                      <span className={`column-dot ${column.tone}`} />
                      <h2>{column.label}</h2>
                      <span>{tasks.length}</span>
                    </div>
                    <div className="task-column-list">
                      {tasks.map((task) => (
                        <TaskCard
                          key={task.id}
                          task={task}
                          onStatusChange={(status) =>
                            updateTask.mutate({ taskId: task.id, status })
                          }
                        />
                      ))}
                      {!tasks.length ? <div className="empty-column">暂无任务</div> : null}
                    </div>
                  </section>
                );
              })}
            </div>
          </>
        ) : null}
      </StateCard>
      <Modal
        title="创建行动计划"
        open={createOpen}
        okText="创建"
        cancelText="取消"
        confirmLoading={createPlan.isPending}
        onCancel={() => setCreateOpen(false)}
        onOk={() => form.submit()}
      >
        <Form form={form} layout="vertical" onFinish={(values) => createPlan.mutate(values)}>
          <Form.Item
            name="goal"
            label="目标"
            rules={[{ required: true, message: '请描述你想完成的目标' }]}
          >
            <Input.TextArea autoSize={{ minRows: 3, maxRows: 6 }} maxLength={500} showCount />
          </Form.Item>
          <Form.Item name="deadline" label="截止日期">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
