import {
  AudioOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  CustomerServiceOutlined,
  ForwardOutlined,
  PhoneOutlined,
  PoweroffOutlined,
  RedoOutlined,
  SafetyCertificateOutlined,
  SoundOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Form,
  List,
  Progress,
  Radio,
  Select,
  Space,
  Spin,
  Steps,
  Statistic,
  Switch,
  Tag,
  Typography,
} from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { PageHeader } from '../../../components/PageHeader';
import { apiClient } from '../../../services/api-client';
import type {
  InterviewDifficulty,
  InterviewReport,
  InterviewSession,
  InterviewTranscriptEntry,
  InterviewTrack,
  InterviewType,
} from '../../../types/domain';
import { InterviewAvatarClient } from '../avatar-client';
import { InterviewRtcClient } from '../rtc-client';

interface SetupValues {
  track: InterviewTrack;
  interviewType: InterviewType;
  difficulty: InterviewDifficulty;
  durationMinutes: number;
  enableAvatar: boolean;
}

const initialValues: SetupValues = {
  track: 'general',
  interviewType: 'mixed',
  difficulty: 'standard',
  durationMinutes: 30,
  enableAvatar: false,
};

export function InterviewPage() {
  const { message, modal } = App.useApp();
  const avatarRef = useRef(new InterviewAvatarClient());
  const rtcRef = useRef(new InterviewRtcClient());
  const avatarContainerRef = useRef<HTMLDivElement>(null);
  const sessionRef = useRef<InterviewSession | undefined>(undefined);
  const elapsedRef = useRef(0);
  const transcriptRef = useRef<InterviewTranscriptEntry[]>([]);
  const [session, setSession] = useState<InterviewSession>();
  const [report, setReport] = useState<InterviewReport>();
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [mediaReady, setMediaReady] = useState(false);
  const [transcriptionEnabled, setTranscriptionEnabled] = useState(true);
  const [phase, setPhase] = useState<'setup' | 'connecting' | 'active' | 'ended'>('setup');
  const readiness = useQuery({
    queryKey: ['interview-readiness'],
    queryFn: apiClient.getInterviewReadiness,
  });

  const recordTranscript = useCallback((text: string) => {
    const entries = transcriptRef.current;
    if (entries.at(-1)?.text !== text) {
      entries.push({ text, recordedAtSeconds: elapsedRef.current });
    }
  }, []);

  useEffect(() => {
    if (phase !== 'active') return;
    const timer = window.setInterval(() => setElapsedSeconds((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [phase]);

  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  useEffect(() => {
    elapsedRef.current = elapsedSeconds;
  }, [elapsedSeconds]);

  useEffect(
    () => () => {
      if (sessionRef.current?.status === 'active') {
        void apiClient.stopInterviewSession(sessionRef.current.id);
      }
      void avatarRef.current.end();
      void rtcRef.current.leave();
    },
    [],
  );

  useEffect(() => {
    if (phase !== 'active' || !session?.enableAvatar || !avatarContainerRef.current) return;
    void avatarRef.current
      .attach(avatarContainerRef.current, recordTranscript)
      .then((enabled) => {
        setTranscriptionEnabled(enabled);
        setMediaReady(true);
        message.success('数字人面试已开始');
      })
      .catch(async (error) => {
        await avatarRef.current.end();
        if (sessionRef.current) {
          await apiClient.stopInterviewSession(sessionRef.current.id).catch(() => undefined);
        }
        setMediaReady(false);
        setSession(undefined);
        setPhase('setup');
        message.error(error instanceof Error ? error.message : '数字人画面启动失败');
      });
  }, [message, phase, recordTranscript, session?.enableAvatar]);

  const startInterview = useMutation({
    mutationFn: async (values: SetupValues) => {
      setPhase('connecting');
      const created = await apiClient.createInterviewSession(values);
      setSession(created);
      setReport(undefined);
      transcriptRef.current = [];
      try {
        if (created.enableAvatar) {
          await avatarRef.current.start(created);
        } else {
          const enabled = await rtcRef.current.join(created, recordTranscript);
          setTranscriptionEnabled(enabled);
          await apiClient.startInterviewSession(created.id);
        }
      } catch (error) {
        await rtcRef.current.leave();
        await apiClient.stopInterviewSession(created.id).catch(() => undefined);
        throw error;
      }
      return { ...created, status: 'active' as const };
    },
    onSuccess: (active) => {
      setSession(active);
      setElapsedSeconds(0);
      setMediaReady(false);
      setPhase('active');
    },
    onError: async (error) => {
      await avatarRef.current.end();
      await rtcRef.current.leave();
      setMediaReady(false);
      setPhase('setup');
      message.error(error instanceof Error ? error.message : '无法开始面试');
    },
  });

  const stopInterview = useMutation({
    mutationFn: async () => {
      await avatarRef.current.end();
      await rtcRef.current.leave();
      if (!session) return undefined;
      await apiClient.stopInterviewSession(session.id);
      return apiClient.generateInterviewReport(session.id, transcriptRef.current);
    },
    onSuccess: (generatedReport) => {
      setMediaReady(false);
      setReport(generatedReport);
      setPhase('ended');
      setSession((value) => (value ? { ...value, status: 'stopped' } : value));
    },
    onError: (error) => {
      setMediaReady(false);
      setPhase('ended');
      message.error(error instanceof Error ? error.message : '面试报告生成失败');
    },
  });

  const controlInterview = useMutation({
    mutationFn: async (command: 'next' | 'repeat') => {
      if (!session || session.enableAvatar) return;
      const prompt = command === 'next'
        ? '候选人请求下一题。请结束当前问题，从面经题库选择一个尚未问过的新问题，只问一个问题，不要解释。'
        : '请简洁重复你刚才提出的问题，不要给答案，也不要切换到新问题。';
      await rtcRef.current.askAgent(session.agentUserId, prompt);
    },
    onSuccess: (_, command) => {
      message.success(command === 'next' ? '已请求下一题' : '已请求重复问题');
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '操作失败'),
  });

  const elapsed = useMemo(() => {
    const minutes = Math.floor(elapsedSeconds / 60).toString().padStart(2, '0');
    const seconds = (elapsedSeconds % 60).toString().padStart(2, '0');
    return `${minutes}:${seconds}`;
  }, [elapsedSeconds]);

  if (readiness.isLoading) {
    return <div className="interview-loading"><Spin size="large" /></div>;
  }

  if (phase === 'ended') {
    return (
      <div className="interview-room interview-report-page">
        <header className="interview-room-header">
          <div><Tag color="success">面试已结束</Tag><strong>前端模拟面试报告</strong></div>
          <Button onClick={() => { setSession(undefined); setReport(undefined); setPhase('setup'); }}>
            再面一次
          </Button>
        </header>
        {report ? (
          <>
            <div className="interview-report-summary">
              <Card>
                <Statistic title="综合得分" value={report.overallScore} suffix="/ 100" />
                <Progress percent={report.overallScore} showInfo={false} strokeColor="#347565" />
              </Card>
              <Card title="面试结论"><Typography.Paragraph>{report.summary}</Typography.Paragraph></Card>
            </div>
            <Card title="能力评分">
              <div className="interview-score-grid">
                {report.scoreItems.map((item) => (
                  <div className="interview-score-item" key={item.key}>
                    <Progress type="circle" size={76} percent={item.score} strokeColor="#347565" />
                    <strong>{item.label}</strong><span>{item.comment}</span>
                  </div>
                ))}
              </div>
            </Card>
            <Card title="问答回顾与逐题点评" extra={<Tag>{report.qaReviews.length} 轮有效回答</Tag>}>
              {report.qaReviews.length ? (
                <List
                  dataSource={report.qaReviews}
                  renderItem={(item, index) => (
                    <List.Item>
                      <div className="interview-qa-review">
                        <div><Tag color="green">{item.score} 分</Tag><strong>Q{index + 1}：{item.question}</strong></div>
                        <p><b>回答：</b>{item.answer}</p>
                        <p><b>点评：</b>{item.feedback}</p>
                      </div>
                    </List.Item>
                  )}
                />
              ) : <Empty description="未获得有效语音转写，暂时无法生成逐题点评" />}
            </Card>
            <div className="interview-report-columns">
              <Card title="表现亮点"><List dataSource={report.strengths} renderItem={(item) => <List.Item>{item}</List.Item>} /></Card>
              <Card title="需要改进"><List dataSource={report.improvements} renderItem={(item) => <List.Item>{item}</List.Item>} /></Card>
              <Card title="下一步行动"><List dataSource={report.nextSteps} renderItem={(item) => <List.Item>{item}</List.Item>} /></Card>
            </div>
            <Alert type="info" showIcon message="报告说明" description="回答来自浏览器语音识别；由于数字人 SDK 不返回面试官字幕，报告中的问题由模型根据回答和本场设置还原。" />
          </>
        ) : <Card><Empty description="报告生成失败，请重新进行面试" /></Card>}
      </div>
    );
  }

  if (phase === 'active') {
    return (
      <div className="interview-room">
        <header className="interview-room-header">
          <div>
            <Tag color={phase === 'active' ? 'green' : 'default'}>
              {phase === 'active' ? '面试进行中' : '面试已结束'}
            </Tag>
            <strong>前端模拟面试</strong>
          </div>
          <Space>
            <ClockCircleOutlined />
            <span>{elapsed}</span>
            <Button
                danger
                icon={<PoweroffOutlined />}
                loading={stopInterview.isPending}
                onClick={() =>
                  modal.confirm({
                    title: '确定结束本次面试？',
                    content: '结束后将关闭麦克风和实时语音房间。',
                    okText: '结束面试',
                    cancelText: '继续面试',
                    okButtonProps: { danger: true },
                    onOk: () => stopInterview.mutateAsync(),
                  })
                }
              >
                结束面试
              </Button>
          </Space>
        </header>
        <div className="interview-room-grid">
          <Card className="interviewer-stage">
            {session?.enableAvatar ? (
              <div ref={avatarContainerRef} className="avatar-video-canvas" />
            ) : (
              <div className="voice-interviewer-placeholder"><CustomerServiceOutlined /></div>
            )}
            {phase === 'active' ? (
              <div className="interview-question-panel">
                <Typography.Title level={3}>
                  {mediaReady || !session?.enableAvatar ? '实时语音面试中' : '数字人正在进入面试间'}
                </Typography.Title>
                <p>
                  {mediaReady || !session?.enableAvatar
                    ? '请直接通过麦克风回答。面试官会根据你的回答连续追问；想跳过时直接说“继续”或“下一题”。'
                    : '正在加载数字人画面和实时语音，请稍候。'}
                </p>
              </div>
            ) : (
              <p>本次语音面试已经结束。面试报告将在后续版本接入。</p>
            )}
            <div className="voice-status">
              <SoundOutlined />
              <span>
                {session?.enableAvatar
                  ? mediaReady
                    ? 'FlowAct-R1 数字人与实时语音已连接'
                    : '正在连接数字人画面与麦克风'
                  : 'AI 面试官与实时语音已连接'}
              </span>
            </div>
            {!session?.enableAvatar ? (
              <Space className="interview-voice-controls" wrap>
                <Button
                  icon={<RedoOutlined />}
                  loading={controlInterview.isPending && controlInterview.variables === 'repeat'}
                  disabled={controlInterview.isPending}
                  onClick={() => controlInterview.mutate('repeat')}
                >
                  重复问题
                </Button>
                <Button
                  type="primary"
                  icon={<ForwardOutlined />}
                  loading={controlInterview.isPending && controlInterview.variables === 'next'}
                  disabled={controlInterview.isPending}
                  onClick={() => controlInterview.mutate('next')}
                >
                  下一题
                </Button>
              </Space>
            ) : null}
            {!transcriptionEnabled && (mediaReady || !session?.enableAvatar) ? (
              <Alert
                type="warning"
                showIcon
                message="当前浏览器不支持语音转写，结束后将无法生成逐题问答报告"
              />
            ) : null}
          </Card>
          <aside className="interview-side-panel">
            <Card title="本场设置">
              <div className="interview-facts">
                <span>方向<strong>{session?.track === 'react' ? 'React' : session?.track === 'vue' ? 'Vue' : '泛前端'}</strong></span>
                <span>类型<strong>{session?.interviewType === 'technical' ? '技术面' : session?.interviewType === 'hr' ? 'HR 面' : '综合面'}</strong></span>
                <span>时长<strong>{session?.durationMinutes} 分钟</strong></span>
              </div>
            </Card>
            <Card title="面试进度">
              <Steps
                direction="vertical"
                size="small"
                current={phase === 'active' ? 1 : 3}
                items={[{ title: '设备与连接' }, { title: '语音面试' }, { title: '能力评分' }, { title: '面试报告' }]}
              />
            </Card>
          </aside>
        </div>
      </div>
    );
  }

  return (
    <div className="page-container interview-page">
      <PageHeader
        eyebrow="Realtime Interview"
        title="AI 模拟面试"
        description="基于真实前端面经进行语音面试，面试官会根据你的回答连续追问。"
        action={
          <Tag color={readiness.data?.configured ? 'success' : 'error'} icon={<SafetyCertificateOutlined />}>
            {readiness.data?.message ?? '服务状态未知'}
          </Tag>
        }
      />
      {!readiness.data?.configured ? (
        <Alert
          type="warning"
          showIcon
          message="实时语音尚未配置"
          description="请在后端 .env 中配置火山引擎 AK/SK 和 RTC AppId/AppKey。"
        />
      ) : null}
      <div className="interview-setup-grid">
        <Card className="surface-card interview-setup-card" title="配置本次面试">
          <Form<SetupValues>
            layout="vertical"
            initialValues={initialValues}
            onFinish={(values) => startInterview.mutate(values)}
          >
            <Form.Item name="track" label="前端方向" rules={[{ required: true }]}> 
              <Radio.Group optionType="button" buttonStyle="solid">
                <Radio.Button value="general">泛前端</Radio.Button>
                <Radio.Button value="react">React</Radio.Button>
                <Radio.Button value="vue">Vue</Radio.Button>
              </Radio.Group>
            </Form.Item>
            <Form.Item name="interviewType" label="面试类型" rules={[{ required: true }]}> 
              <Radio.Group optionType="button" buttonStyle="solid">
                <Radio.Button value="technical">技术面</Radio.Button>
                <Radio.Button value="hr">HR 面</Radio.Button>
                <Radio.Button value="mixed">综合面</Radio.Button>
              </Radio.Group>
            </Form.Item>
            <div className="form-grid">
              <Form.Item name="difficulty" label="难度" rules={[{ required: true }]}> 
                <Select options={[{ value: 'standard', label: '标准' }, { value: 'advanced', label: '进阶' }, { value: 'pressure', label: '压力面' }]} />
              </Form.Item>
              <Form.Item name="durationMinutes" label="预计时长" rules={[{ required: true }]}> 
                <Select options={[15, 30, 45, 60].map((value) => ({ value, label: `${value} 分钟` }))} />
              </Form.Item>
            </div>
            <Form.Item
              name="enableAvatar"
              label="AI 数字人"
              valuePropName="checked"
              extra={readiness.data?.avatar_configured ? '开启后显示实时数字人；关闭时使用更稳定的纯语音面试。' : '数字人服务尚未配置，可使用纯语音面试。'}
            >
              <Switch checkedChildren="开启" unCheckedChildren="关闭" disabled={!readiness.data?.avatar_configured} />
            </Form.Item>
            <Button
              type="primary"
              size="large"
              block
              htmlType="submit"
              icon={<PhoneOutlined />}
              loading={startInterview.isPending || phase === 'connecting'}
              disabled={!readiness.data?.configured}
            >
              {phase === 'connecting' ? '正在进入面试房间' : '检查麦克风并开始面试'}
            </Button>
          </Form>
        </Card>
        <div className="interview-intro">
          <Card className="interview-preview-card">
            <div className="preview-avatar"><CustomerServiceOutlined /></div>
            <div>
              <span>你的面试官</span>
              <h2>AI 前端面试官</h2>
              <p>覆盖 JavaScript、React、Vue、浏览器、性能优化、微前端和工程化。</p>
            </div>
          </Card>
          <Card title="开始前确认">
            <ul className="interview-checklist">
              <li><CheckCircleFilled /> 使用耳机可以减少回声</li>
              <li><CheckCircleFilled /> 浏览器将请求麦克风权限</li>
              <li><CheckCircleFilled /> 面试过程中不会展示参考答案</li>
              <li><AudioOutlined /> 支持自然停顿和语音打断</li>
            </ul>
          </Card>
          <Card size="small">
            <div className="interview-progress-copy">
              <span>面经知识准备度</span><strong>已导入首批前端面经</strong>
            </div>
            <Progress percent={68} showInfo={false} strokeColor="#347565" />
          </Card>
        </div>
      </div>
    </div>
  );
}
