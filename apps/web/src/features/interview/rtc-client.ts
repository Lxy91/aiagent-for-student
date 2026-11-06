import VERTC, { type IRTCEngine } from '@volcengine/rtc';
import type { InterviewSession } from '../../types/domain';

export class InterviewRtcClient {
  private engine?: IRTCEngine;
  private recognition?: SpeechRecognitionLike;
  private keepRecognizing = false;
  private onTranscript?: (text: string) => void;

  async join(session: InterviewSession, onTranscript: (text: string) => void, onAgentSubtitle?: (text: string, newRound: boolean) => void) {
    const permission = await VERTC.enableDevices({ audio: true, video: false });
    if (!permission.audio) throw new Error('请允许浏览器使用麦克风');
    const engine = VERTC.createEngine(session.appId);
    engine.on(VERTC.events.onError, (payload) => console.error('VeRTC error', payload));
    const sentences = new Map<number, string>();
    let roundId: number | undefined;
    engine.on(VERTC.events.onRoomBinaryMessageReceived, ({ message }) => {
      for (const subtitle of parseInterviewSubtitles(message)) {
        if (subtitle.userId !== session.agentUserId) continue;
        const newRound = roundId !== subtitle.roundId;
        if (newRound) {
          void this.setAnswering(false);
          sentences.clear();
          roundId = subtitle.roundId;
        }
        sentences.set(subtitle.sequence, subtitle.text);
        onAgentSubtitle?.([...sentences.entries()].sort(([a], [b]) => a - b).map(([, text]) => text).join(''), newRound);
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
    await this.sendControl(agentUserId, {
      Command: 'ExternalTextToLLM',
      Message: message,
      InterruptMode: 1,
    });
  }

  async speak(agentUserId: string, message: string) {
    await this.sendControl(agentUserId, {
      Command: 'ExternalTextToSpeech',
      Message: message,
      InterruptMode: 1,
    });
  }

  private async sendControl(agentUserId: string, payload: Record<string, unknown>) {
    if (!this.engine) throw new Error('实时语音房间尚未连接');
    const content = new TextEncoder().encode(JSON.stringify(payload));
    const packet = new Uint8Array(8 + content.length);
    packet.set(new TextEncoder().encode('ctrl'), 0);
    new DataView(packet.buffer).setUint32(4, content.length, false);
    packet.set(content, 8);
    await this.engine.sendUserBinaryMessage(agentUserId, packet.buffer);
  }

  async leave() {
    this.stopTranscription();
    if (!this.engine) return;
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
