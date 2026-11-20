import { logInterviewDiagnostic } from '../../services/api-client';
import VERTC, { type IRTCEngine } from '@volcengine/rtc';
import type { InterviewSession } from '../../types/domain';

export class InterviewRtcClient {
  private sessionId = '';
  private requestId = '';
  private requestStarted = 0;
  private engine?: IRTCEngine;
  private recognition?: SpeechRecognitionLike;
  private keepRecognizing = false;
  private onTranscript?: (text: string) => void;
  private lastRoundId?: number;
  private pendingRound?: { resolve: () => void; reject: (error: Error) => void; timeout: number };
  private pendingDecision?: { resolve: (decision: 'follow_up' | 'new_question') => void; timeout: number };

  async join(session: InterviewSession, onTranscript: (text: string) => void, onAgentSubtitle?: (text: string, newRound: boolean) => void) {
    this.sessionId = session.id;
    this.requestId = "";
    this.requestStarted = performance.now();
    logInterviewDiagnostic(this.sessionId, 'rtc_join_start');
    const permission = await VERTC.enableDevices({ audio: true, video: false });
    if (!permission.audio) throw new Error('请允许浏览器使用麦克风');
    const engine = VERTC.createEngine(session.appId);
    engine.on(VERTC.events.onConnectionStateChanged, event => logInterviewDiagnostic(this.sessionId, 'connection_state', this.requestId, 0, JSON.stringify(event).slice(0, 300)));
    engine.on(VERTC.events.onError, (payload) => { console.error('VeRTC error', payload); logInterviewDiagnostic(this.sessionId, 'rtc_error'); });
    const sentences = new Map<number, string>();
    engine.on(VERTC.events.onRoomBinaryMessageReceived, ({ message }) => {
      for (const subtitle of parseInterviewSubtitles(message)) {
        if (subtitle.userId !== session.agentUserId) continue;
        logInterviewDiagnostic(this.sessionId, 'subtitle_received', this.requestId, performance.now() - this.requestStarted, `round=${subtitle.roundId},sequence=${subtitle.sequence},length=${subtitle.text.length}`);
        // A nonempty agent subtitle is the response, even when the service
        // reuses a round id. Do not keep the UI blocked on round metadata.
        if (this.pendingRound && subtitle.text.trim()) {
          window.clearTimeout(this.pendingRound.timeout);
          this.pendingRound.resolve();
          this.pendingRound = undefined;
        }
        const newRound = this.lastRoundId !== subtitle.roundId;
        if (newRound) {
          void this.setAnswering(false);
          sentences.clear();
          this.lastRoundId = subtitle.roundId;
          if (this.pendingRound) {
            window.clearTimeout(this.pendingRound.timeout);
            this.pendingRound.resolve();
            this.pendingRound = undefined;
          }
        }
        sentences.set(subtitle.sequence, subtitle.text);
        const fullText = [...sentences.entries()].sort(([a], [b]) => a - b).map(([, text]) => text).join('');
        if (this.pendingDecision && /FOLLOW_UP|NEW_QUESTION/.test(fullText)) {
          const decision = fullText.includes('FOLLOW_UP') ? 'follow_up' : 'new_question';
          window.clearTimeout(this.pendingDecision.timeout);
          this.pendingDecision.resolve(decision);
          this.pendingDecision = undefined;
          return;
        }
        onAgentSubtitle?.(fullText, newRound);
      }
    });
    this.engine = engine;
    await engine.joinRoom(
      session.token,
      session.roomId,
      {
        userId: session.userId,
        extraInfo: JSON.stringify({
          call_scene: 'RTC-AIGC',
          user_name: session.userId,
          user_id: session.userId,
        }),
      },
      { isAutoPublish: true, isAutoSubscribeAudio: true, roomProfileType: 0 },
    );
    this.onTranscript = onTranscript;
    const target = window as unknown as SpeechRecognitionWindow;
    return !!(target.SpeechRecognition ?? target.webkitSpeechRecognition);
  }

  async setAnswering(enabled: boolean) {
    this.stopTranscription();
    if (!this.engine) return;
    if (enabled) {
      await this.engine.startAudioCapture();
      if (this.onTranscript) this.startTranscription(this.onTranscript);
    } else {
      await this.engine.stopAudioCapture();
    }
  }

  async askAgent(agentUserId: string, message: string) {
    try {
      await this.requestQuestion(agentUserId, message);
    } catch (error) {
      if (!(error instanceof Error) || !error.message.includes('面试官暂未响应')) throw error;
      logInterviewDiagnostic(this.sessionId, 'question_retry', this.requestId);
      await this.requestQuestion(agentUserId, message);
    }
  }

  private async requestQuestion(agentUserId: string, message: string) {
    this.requestId = crypto.randomUUID();
    this.requestStarted = performance.now();
    logInterviewDiagnostic(this.sessionId, 'question_request', this.requestId);
    if (this.pendingRound) throw new Error('正在等待面试官响应，请稍候');
    let resolveRound!: () => void;
    let rejectRound!: (error: Error) => void;
    const roundResponse = new Promise<void>((resolve, reject) => {
      resolveRound = resolve;
      rejectRound = reject;
    });
    const timeout = window.setTimeout(() => {
      if (this.pendingRound?.reject === rejectRound) this.pendingRound = undefined;
      logInterviewDiagnostic(this.sessionId, 'question_timeout', this.requestId, performance.now() - this.requestStarted);
      rejectRound(new Error('面试官暂未响应，请重试本题'));
    }, 20_000);
    this.pendingRound = { resolve: resolveRound, reject: rejectRound, timeout };
    // A control response may reuse the provider round id.
    this.lastRoundId = undefined;
    try {
      const sending = this.sendControl(agentUserId, {
      Command: 'ExternalTextToLLM',
      Message: message,
      InterruptMode: 1,
      });
      void sending.catch(error => {
        if (this.pendingRound?.reject === rejectRound) {
          window.clearTimeout(timeout);
          this.pendingRound = undefined;
          rejectRound(error instanceof Error ? error : new Error('切题请求发送失败，请重试'));
        }
      });
      await roundResponse;
    } catch (error) {
      window.clearTimeout(timeout);
      if (this.pendingRound?.reject === rejectRound) this.pendingRound = undefined;
      throw error;
    }
    await roundResponse;
    logInterviewDiagnostic(this.sessionId, 'question_response', this.requestId, performance.now() - this.requestStarted);
  }

  async speak(agentUserId: string, message: string) {
    await this.sendControl(agentUserId, {
      Command: 'ExternalTextToSpeech',
      Message: message,
      InterruptMode: 1,
    });
  }

  async decideNextAction(agentUserId: string, answer: string): Promise<'follow_up' | 'new_question'> {
    // Keep classification out of the live speech channel: a second LLM command
    // can interrupt the classification or consume the next question's response.
    const substantive = answer.trim().length >= 40 && /项目|实现|负责|优化|方案|结果|解决|设计|性能|协作/.test(answer);
    return substantive ? 'follow_up' : 'new_question';
  }

  private async sendControl(agentUserId: string, payload: Record<string, unknown>) {
    if (!this.engine) throw new Error('实时语音房间尚未连接');
    const content = new TextEncoder().encode(JSON.stringify(payload));
    const packet = new Uint8Array(8 + content.length);
    packet.set(new TextEncoder().encode('ctrl'), 0);
    new DataView(packet.buffer).setUint32(4, content.length, false);
    packet.set(content, 8);
    const started = performance.now();
    logInterviewDiagnostic(this.sessionId, 'control_send_start', this.requestId);
    try {
      const result = await this.engine.sendUserBinaryMessage(agentUserId, packet.buffer);
      logInterviewDiagnostic(this.sessionId, 'control_send_ack', this.requestId, performance.now() - started, `result=${String(result).slice(0, 100)}`);
    } catch (error) {
      logInterviewDiagnostic(this.sessionId, 'control_send_error', this.requestId, performance.now() - started);
      throw error;
    }
  }

  async leave() {
    this.stopTranscription();
    if (!this.engine) return;
    if (this.pendingRound) {
      window.clearTimeout(this.pendingRound.timeout);
      this.pendingRound.reject(new Error('面试语音连接已关闭'));
      this.pendingRound = undefined;
    }
    if (this.pendingDecision) {
      window.clearTimeout(this.pendingDecision.timeout);
      this.pendingDecision.resolve('new_question');
      this.pendingDecision = undefined;
    }
    this.lastRoundId = undefined;
    try {
      await this.engine.stopAudioCapture();
      await this.engine.leaveRoom();
    } finally {
      VERTC.destroyEngine(this.engine);
      this.engine = undefined;
    }
  }

  private startTranscription(onTranscript: (text: string) => void) {
    const target = window as unknown as SpeechRecognitionWindow;
    const Recognition = target.SpeechRecognition ?? target.webkitSpeechRecognition;
    if (!Recognition) return false;
    const recognition = new Recognition();
    recognition.lang = 'zh-CN';
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const text = result[0]?.transcript.trim();
        if (this.recognition === recognition && this.keepRecognizing && result.isFinal && text) onTranscript(text);
      }
    };
    recognition.onend = () => {
      if (!this.keepRecognizing) return;
      window.setTimeout(() => {
        if (!this.keepRecognizing || this.recognition !== recognition) return;
        try { recognition.start(); } catch { /* browser is already restarting */ }
      }, 300);
    };
    this.recognition = recognition;
    this.keepRecognizing = true;
    try { recognition.start(); return true; } catch { this.stopTranscription(); return false; }
  }

  private stopTranscription() {
    this.keepRecognizing = false;
    const recognition = this.recognition;
    this.recognition = undefined;
    if (!recognition) return;
    recognition.onend = null;
    try { recognition.stop(); } catch { /* already stopped */ }
  }
}

interface SpeechRecognitionResultLike { isFinal: boolean; 0?: { transcript: string } }
interface SpeechRecognitionEventLike { resultIndex: number; results: ArrayLike<SpeechRecognitionResultLike> }
interface SpeechRecognitionLike {
  lang: string; continuous: boolean; interimResults: boolean;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onend: (() => void) | null;
  start(): void; stop(): void;
}
interface SpeechRecognitionWindow {
  SpeechRecognition?: new () => SpeechRecognitionLike;
  webkitSpeechRecognition?: new () => SpeechRecognitionLike;
}

interface InterviewSubtitle {
  userId: string;
  text: string;
  sequence: number;
  roundId: number;
}

export function parseInterviewSubtitles(message: ArrayBuffer): InterviewSubtitle[] {
  if (message.byteLength < 8) return [];
  const bytes = new Uint8Array(message);
  if (new TextDecoder().decode(bytes.subarray(0, 4)) !== 'subv') return [];
  if (new DataView(message).getUint32(4, false) !== message.byteLength - 8) return [];
  try {
    const payload = JSON.parse(new TextDecoder().decode(bytes.subarray(8)));
    if (payload?.type !== 'subtitle' || !Array.isArray(payload.data)) return [];
    return payload.data.filter((item: Partial<InterviewSubtitle> | null): item is InterviewSubtitle =>
      !!item && typeof item.userId === 'string' && typeof item.text === 'string' &&
      Number.isInteger(item.sequence) && Number.isInteger(item.roundId));
  } catch { return []; }
}
