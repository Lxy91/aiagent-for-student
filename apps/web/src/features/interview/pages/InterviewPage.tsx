import { useLocation, useNavigate } from 'react-router-dom';
import {
  AudioOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  CustomerServiceOutlined,
  ForwardOutlined,
  PhoneOutlined,
  PoweroffOutlined,
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
  Tooltip,
  Tabs,
} from 'antd';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { PageHeader } from '../../../components/PageHeader';
import { uploadInterviewClip, loadInterviewClip, completeInterview, getInterviewHistory, apiClient } from '../../../services/api-client';
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
  const navigate = useNavigate();
  const location = useLocation();
  const showHistory = location.pathname === '/interview/history';
  const history = useQuery({ queryKey: ['interview-history'], queryFn: getInterviewHistory, enabled: showHistory, refetchInterval: showHistory ? 5000 : false });
  const camera = useRef<MediaStream | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const attachCameraPreview = useCallback((element: HTMLVideoElement | null) => {
    if (element && element.srcObject !== camera.current) {
      element.srcObject = camera.current;
    }
  }, []);
  const [clips, setClips] = useState<Array<{ question: string; url: string; main: number; followUp: boolean; answer: string }>>([]);
  const clipsRef = useRef(clips);
  const questionRef = useRef('自我介绍');
  const roundRef = useRef(1);
  const followUpRef = useRef(false);
  const reverseRef = useRef(false);
  const answerStartRef = useRef(0);
  const stopClip = useCallback(async () => {
    const active = recorder.current;
    if (active && active.state !== 'inactive') await new Promise<void>(resolve => {
      active.addEventListener('stop', () => resolve(), { once: true });
      active.stop();
    });
  }, []);
  const startClip = () => {
    if (!camera.current || recorder.current?.state === 'recording') return;
    const chunks: Blob[] = [];
    const question = questionRef.current;
    const main = roundRef.current;
    const followUp = followUpRef.current;
    answerStartRef.current = transcriptRef.current.length;
    const capture = new MediaRecorder(camera.current);
    recorder.current = capture;
    capture.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    capture.onstop = () => {
      const url = URL.createObjectURL(new Blob(chunks, { type: capture.mimeType }));
      clipsRef.current = [...clipsRef.current, { question, url, main, followUp, answer: transcriptRef.current.slice(answerStartRef.current).map(entry => entry.text).join(' ') }];
      setClips(clipsRef.current);
    };
    capture.start(1000);
  };
  const saveRecording = async () => {
    await stopClip();
    camera.current?.getTracks().forEach(track => track.stop());
  };
  const avatarRef = useRef(new InterviewAvatarClient());
  const rtcRef = useRef(new InterviewRtcClient());
  const avatarContainerRef = useRef<HTMLDivElement>(null);
  const sessionRef = useRef<InterviewSession | undefined>(undefined);
  const elapsedRef = useRef(0);
  const transcriptRef = useRef<InterviewTranscriptEntry[]>([]);
  const controlInFlightRef = useRef(false);
  const controlRequestIdRef = useRef(0);
  const [session, setSession] = useState<InterviewSession>();
  const [report, setReport] = useState<InterviewReport>();
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [phase, setPhase] = useState<'setup' | 'connecting' | 'active' | 'ended'>('setup');
  const [agentSubtitle, setAgentSubtitle] = useState('');
  const [visibleSubtitle, setVisibleSubtitle] = useState('');
  const [answerPhase, setAnswerPhase] = useState<'waiting' | 'preparing' | 'answering' | 'finished'>('waiting');
  const [interviewQuestionsFinished, setInterviewQuestionsFinished] = useState(false);
  const [questionDeadline, setQuestionDeadline] = useState(0);
  const [remainingSeconds, setRemainingSeconds] = useState(30);

  const receiveSubtitle = useCallback((text: string, newRound: boolean) => {
    if (reverseRef.current && !/反问时间|本场面试问答环节已结束/.test(text)) return;
    questionRef.current = text;
    setAgentSubtitle(text);
    if (/题库.*(全部|所有).*(提问完毕|问完)|没有剩余.*新问题|问答环节.*结束/.test(text)) {
      setAnswerPhase('finished');
      setQuestionDeadline(0);
      void rtcRef.current.setAnswering(false).catch(() => message.error('关闭麦克风失败，请结束面试'));
      return;
    }
    if (newRound) {
      setVisibleSubtitle('');
      setAnswerPhase('preparing');
      setQuestionDeadline(Date.now() + 30_000);
      setRemainingSeconds(30);
    }
  }, [message]);

  useEffect(() => {
    if (visibleSubtitle === agentSubtitle) return;
    const timer = window.setTimeout(() => {
      setVisibleSubtitle((current) => agentSubtitle.slice(0, current.length + 1));
    }, 45);
    return () => window.clearTimeout(timer);
  }, [agentSubtitle, visibleSubtitle]);

  const beginAnswer = useMutation({
    mutationFn: async () => {
      await rtcRef.current.setAnswering(true);
      startClip();
    },
    onSuccess: () => {
      automaticStartDeadline.current = 0;
      setAnswerPhase('answering');
      setQuestionDeadline(Date.now() + 180_000);
      setRemainingSeconds(180);
    },
    onError: () => {
      setAnswerPhase('preparing');
      message.error('麦克风启动失败，请检查麦克风权限后点击“我准备好了”重试');
    },
  });

  const automaticStartDeadline = useRef(0);

  useEffect(() => {
    if (phase !== 'active' || !questionDeadline || !['preparing', 'answering'].includes(answerPhase)) return;
    const update = () => {
      const remaining = Math.max(0, Math.ceil((questionDeadline - Date.now()) / 1000));
      setRemainingSeconds(remaining);
      if (!remaining && answerPhase === 'preparing' && !beginAnswer.isPending && automaticStartDeadline.current !== questionDeadline) {
        automaticStartDeadline.current = questionDeadline;
        beginAnswer.mutate();
      }
      if (!remaining && answerPhase === 'answering') {
        void stopClip();
        setAnswerPhase('finished');
        void rtcRef.current.setAnswering(false).catch(() => message.error('关闭麦克风失败，请结束面试'));
      }
    };
    update();
    const timer = window.setInterval(update, 250);
    return () => window.clearInterval(timer);
  }, [answerPhase, questionDeadline, phase, message, beginAnswer.isPending, beginAnswer.mutate]);


  const [mediaReady, setMediaReady] = useState(false);
  const [transcriptionEnabled, setTranscriptionEnabled] = useState(true);

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
      recorder.current?.state === "recording" && recorder.current.stop();
      camera.current?.getTracks().forEach(track => track.stop());
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
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('请使用支持摄像头录制的浏览器，并通过 HTTPS 或 localhost 访问');
      camera.current = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      clips.forEach(clip => URL.revokeObjectURL(clip.url));
      setClips([]);
      clipsRef.current = [];
      roundRef.current = 1;
      followUpRef.current = false;
      reverseRef.current = false;
      const created = await apiClient.createInterviewSession(values);
      setSession(created);
      setReport(undefined);
      transcriptRef.current = [];
      setAgentSubtitle('');
      setVisibleSubtitle('');
      setAnswerPhase('waiting');
      setQuestionDeadline(0);
      setInterviewQuestionsFinished(false);
      try {
        if (created.enableAvatar) {
          await avatarRef.current.start(created);
        } else {
          const enabled = await rtcRef.current.join(created, recordTranscript, receiveSubtitle);
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
      await saveRecording();
      await avatarRef.current.end();
      await rtcRef.current.leave();
      setMediaReady(false);
      setPhase('setup');
      message.error(error instanceof Error ? error.message : '无法开始面试');
    },
  });

  const stopInterview = useMutation({
    mutationFn: async () => {
      await saveRecording();
      await avatarRef.current.end();
      await rtcRef.current.leave();
      if (!session) return undefined;
      for (const clip of clipsRef.current) await uploadInterviewClip(session.id, clip);
      return completeInterview(session.id, clipsRef.current.map(clip => ({ text: clip.answer, question: clip.question, recordedAtSeconds: 0 })));
    },
    onSuccess: () => {
      setMediaReady(false);
      setReport(undefined);
      setPhase('setup');
      message.success('面试已完成，报告正在后台生成，可在面试记录查看');
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
      const requestId = ++controlRequestIdRef.current;
      controlInFlightRef.current = true;
      setAnswerPhase('waiting');
      setQuestionDeadline(0);
      try {
        await rtcRef.current.setAnswering(false);
        await stopClip();
        if (command === 'repeat') {
          await rtcRef.current.askAgent(session.agentUserId, '请仅重复当前问题，不得换题。');
        } else if (reverseRef.current) {
          setInterviewQuestionsFinished(true);
          setAnswerPhase('finished');
          await stopInterview.mutateAsync();
        } else if (!followUpRef.current && elapsedRef.current < session.durationMinutes * 60 - 120 &&
          transcriptRef.current.slice(answerStartRef.current).length > 0 &&
          await rtcRef.current.decideNextAction(session.agentUserId, transcriptRef.current.slice(answerStartRef.current).map(entry => entry.text).join(' ')) === 'follow_up') {
          await rtcRef.current.askAgent(session.agentUserId, `针对当前第${roundRef.current}道主问题的回答追问一个具体细节，不得切换主题。本次属于追问，不增加主问题计数。`);
          followUpRef.current = true;
        } else if (roundRef.current >= 8 || elapsedRef.current >= session.durationMinutes * 60 - 120) {
          reverseRef.current = true;
          roundRef.current = 9;
          followUpRef.current = false;
          const invitation = '考察环节已经完成。接下来是你的反问时间，你有什么想了解或想问我的问题吗？没有也可以直接结束并生成报告。';
          receiveSubtitle(invitation, true);
          await rtcRef.current.speak(session.agentUserId, invitation);
        } else {
          const nextRound = roundRef.current + 1;
          const stage = session.interviewType === 'hr' ? 'HR' : session.interviewType === 'mixed' && nextRound >= 6 ? 'HR' : '技术';
          await rtcRef.current.askAgent(session.agentUserId,
            `当前是第 ${nextRound}/8 题，属于${stage}阶段。严格只问一道尚未问过的${stage}问题。${stage === 'HR' ? '技术阶段已结束，禁止返回技术八股或技术追问。' : '围绕题库进行技术考察。'}不要自行继续提问，等待用户点击下一题。`);
          roundRef.current = nextRound;
          followUpRef.current = false;
        }
      } catch (error) {
        if (controlRequestIdRef.current === requestId) {
          controlInFlightRef.current = false;
          setAnswerPhase('finished');
        }
        throw error;
      }
      if (controlRequestIdRef.current === requestId) controlInFlightRef.current = false;
    },
    onSuccess: (_, command) => {
      message.success(command === 'next' ? '面试官已开始下一题' : '面试官正在重复问题');
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '操作失败'),
    onSettled: () => {
      controlInFlightRef.current = false;
    },
  });

  const waitingForQuestion = controlInterview.isPending && answerPhase === 'waiting';

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
            {showHistory ? '返回面试记录' : '再面一次'}
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
              <svg viewBox="0 0 440 340" style={{ width: '100%', maxHeight: 340 }} role="img" aria-label="面试能力雷达图">
                {[20,40,60,80,100].map(level => <polygon key={level} points={report.scoreItems.map((_, i) => { const angle = i * Math.PI * 2 / report.scoreItems.length - Math.PI / 2; return `${220 + Math.cos(angle)*level*1.1},${165 + Math.sin(angle)*level*1.1}`; }).join(' ')} fill="#f4f1ff" stroke="#ded8ef" />)}
                <polygon points={report.scoreItems.map((item, i) => { const angle = i*Math.PI*2/report.scoreItems.length-Math.PI/2; return `${220+Math.cos(angle)*item.score*1.1},${165+Math.sin(angle)*item.score*1.1}`; }).join(' ')} fill="#8274ec55" stroke="#8274ec" strokeWidth="3" />
                {report.scoreItems.map((item,i) => { const angle=i*Math.PI*2/report.scoreItems.length-Math.PI/2; return <text key={item.key} x={220+Math.cos(angle)*145} y={165+Math.sin(angle)*145} textAnchor="middle" fontSize="13"><title>{item.comment}</title>{item.label} {item.score}</text>; })}
              </svg>
              <div className="interview-score-grid">
                {report.scoreItems.map((item) => (
                  <div className="interview-score-item" key={item.key}>
                    <Progress type="circle" size={76} percent={item.score} strokeColor="#347565" />
                    <Tooltip title={`评分依据：${({ fundamentals: '知识准确性、原理理解与边界条件', framework: '框架原理、实际应用和方案取舍', engineering: '工程实践、性能优化与可维护性', communication: '回答相关性、清晰度、结构和完整性；转写无法可靠判断语速或自信程度', problem_solving: '问题拆解、解决步骤、验证和结果' })[item.key]}。本次表现：${item.comment}`}><strong tabIndex={0}>{item.label} ⓘ</strong></Tooltip><span>{item.comment}</span>
                  </div>
                ))}
              </div>
            </Card>
            <Card title="问题回顾">
              <Tabs destroyOnHidden items={Array.from(new Set(clips.map(clip => clip.main))).map(main => ({
                key: String(main), label: main === 9 ? '反问环节' : `问题${main}`,
                children: clips.filter(clip => clip.main === main).map((clip, index) => {
                  const review = report.qaReviews.find(item => item.question === clip.question);
                  return <div key={clip.url}>
                    <Typography.Title level={5}>{clip.question}</Typography.Title>
                    <video controls preload="metadata" src={clip.url} style={{ width: '100%', maxHeight: 320 }} />
                    <Button href={clip.url} download={`answer-${main}-${index}.webm`}>下载本段回答</Button>
                    <p><b>你的回答：</b>{review?.answer || '未获得与本题匹配的有效转写'}</p>
                    {review ? <><p><b>考察点：</b>{review.assessment}</p><p><b>优缺点分析：</b>{review.feedback}</p><p><b>AI 推荐回答：</b>{review.sampleAnswer || 'AI 推荐回答暂未生成，请稍后重试'}</p></> : <p>本题 AI 推荐回答暂未生成。</p>}
                  </div>;
                }),
              }))} />
              {!clips.length && <Tabs items={report.qaReviews.map((item,index) => ({ key: String(index), label: `问题${index+1}`, children: <div><h3>{item.question}</h3><p>你的回答：{item.answer}</p><p>考察点：{item.assessment}</p><p>分析：{item.feedback}</p><p>AI 推荐回答：{item.sampleAnswer}</p></div> }))} />}
              <p>录像与面试记录保存三天，到期自动清理。</p>
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

  if (showHistory) {
    return <div className="page-container interview-page">
      <PageHeader title="面试记录" description="查看近三天的面试报告和逐题录像，到期自动清理。" action={<Button onClick={() => navigate('/interview')}>返回面试入口</Button>} />
      <Card title="面试记录（保留三天）"><List loading={history.isLoading} dataSource={history.data ?? []} locale={{ emptyText: '暂无面试记录' }} renderItem={item => <List.Item actions={[<Button key="view" disabled={!item.report} onClick={async () => { try { const saved = await Promise.all((item.clips ?? []).map(async clip => ({ ...clip, answer: '', url: await loadInterviewClip(item.id, clip.id) }))); setReport(item.report); setClips(saved); setPhase('ended'); } catch { message.error('录像加载失败，请重试'); } }}>查看报告</Button>]}><List.Item.Meta title={new Date(item.created_at).toLocaleString()} description={item.status === 'completed' ? '报告已生成' : item.status === 'failed' ? '报告生成失败' : '报告生成中'} /></List.Item>} /></Card>
    </div>;
  }

  if (phase === 'active') {
    return (
      <div className="interview-room">
        <header className="interview-room-header">
          <div>
            <Tag color={phase === 'active' ? 'green' : 'default'}>
              {phase === 'active' ? '面试进行中' : '面试已结束'}
            </Tag>
            <strong>前端模拟面试 · {reverseRef.current ? '反问环节' : `第 ${roundRef.current} 题 / 共 8 题`}</strong>
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
                完成面试
              </Button>
          </Space>
        </header>
        <div className="interview-room-grid">
          <Card className={`interviewer-stage${session?.enableAvatar ? "" : " voice-interview-stage"}${waitingForQuestion ? ' interview-thinking' : ''}`}>
            {session?.enableAvatar ? (
              <div ref={avatarContainerRef} className="avatar-video-canvas" />
            ) : (
              <div className="voice-interviewer-portrait-panel">
                <p className="interview-stage-hint">{waitingForQuestion ? '面试官正在思考下一题，请稍候…' : interviewQuestionsFinished ? '题库问题已完成，可以完成面试。' : answerPhase === 'answering' ? '正在录音，每题最多作答 3 分钟。' : answerPhase === 'finished' ? '麦克风已关闭，可继续下一题或结束面试生成报告。' : '准备阶段不录音；30 秒后自动进入作答并录制，也可点击“我准备好了”提前开始。'}</p>
                <img className="voice-interviewer-portrait" src="/images/interviewer.png" alt="AI 面试官" />
                <strong>面试官</strong>
                <div className="interview-stage-countdown" aria-live="polite">
                <Tag color={answerPhase === 'answering' ? 'green' : 'default'}>
                  {waitingForQuestion ? <><Spin size="small" /> 面试官思考中</> : interviewQuestionsFinished ? '问题已问完' : answerPhase === 'preparing' ? `思考时间 ${remainingSeconds}s` : answerPhase === 'answering' ? `作答剩余 ${Math.floor(remainingSeconds / 60)}:${String(remainingSeconds % 60).padStart(2, '0')}` : answerPhase === 'finished' ? '本题作答已结束' : '等待面试官提问'}
                </Tag>

                </div>
                <Progress className="interview-stage-timebar" percent={['preparing', 'answering'].includes(answerPhase) ? remainingSeconds / (answerPhase === 'preparing' ? 30 : 180) * 100 : 0} showInfo={false} strokeColor="#347565" strokeLinecap="butt" />
              </div>
            )}
            {phase === 'active' ? (
              <div className="interview-question-panel">
                <Typography.Title level={3}>
                  {!session?.enableAvatar ? '面试官' : mediaReady ? '实时语音面试中' : '数字人正在进入面试间'}
                </Typography.Title>
                <p>
                  {!session?.enableAvatar
                    ? visibleSubtitle || '正在等待面试官讲话，请通过麦克风回答。'
                    : mediaReady
                    ? '请直接通过麦克风回答。面试官会根据你的回答连续追问；想跳过时直接说“继续”或“下一题”。'
                    : '正在加载数字人画面和实时语音，请稍候。'}
                </p>
              </div>
            ) : (
              <p>本次语音面试已经结束。面试报告将在后续版本接入。</p>
            )}
            {!session?.enableAvatar && (
              <div className="interview-answer-timer" aria-live="polite">
                {answerPhase === 'preparing' && <Button type="primary" loading={beginAnswer.isPending} onClick={() => { automaticStartDeadline.current = questionDeadline; beginAnswer.mutate(); }}>我准备好了</Button>}

              </div>
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
                {answerPhase === 'answering' && <Button type="primary" onClick={async () => {
                  try {
                    await stopClip();
                    await rtcRef.current.setAnswering(false);
                    setAnswerPhase('finished');
                    setQuestionDeadline(0);
                    if (reverseRef.current) await stopInterview.mutateAsync();
                  } catch { message.error('关闭麦克风失败，请重试'); }
                }}>回答完毕</Button>}
                {answerPhase === 'finished' && !interviewQuestionsFinished && <Button
                  type="primary"
                  icon={<ForwardOutlined />}
                  loading={controlInterview.isPending && controlInterview.variables === 'next'}
                  disabled={controlInterview.isPending || controlInFlightRef.current}
                  onClick={() => controlInterview.mutate('next')}
                >
                  下一题
                </Button>}
                {interviewQuestionsFinished && <Button type="primary" danger icon={<PoweroffOutlined />} loading={stopInterview.isPending} onClick={() => stopInterview.mutate()}>完成面试</Button>}
              </Space>
            ) : null}
            {!transcriptionEnabled && (mediaReady || !session?.enableAvatar) ? (
              <Alert
                type="warning"
                showIcon
                message="当前浏览器不支持语音转写，结束后将无法生成逐题问答报告"
              />
            ) : null}
            {waitingForQuestion && (
              <div className="interview-thinking-overlay" role="status" aria-live="polite">
                <Spin size="large" />
                <strong>面试官正在准备下一轮问题</strong>
                <span>正在结合本轮回答思考，请稍候…</span>
              </div>
            )}
          </Card>
          <aside className="interview-side-panel">
            <Card title={answerPhase === 'answering' ? "摄像头 · 本题录制中" : "摄像头 · 预览（未录制）"}><video autoPlay muted playsInline ref={attachCameraPreview} style={{ width: '100%', aspectRatio: '4 / 3', objectFit: 'cover', background: '#172923', borderRadius: 12 }} /></Card>
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
      <Button onClick={() => navigate('/interview/history')}>面试记录</Button>

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
              {phase === 'connecting' ? '正在进入面试房间' : '开启摄像头并开始面试'}
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
              <li><CheckCircleFilled /> 浏览器将请求摄像头与麦克风权限，结束后请下载录像</li>
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
