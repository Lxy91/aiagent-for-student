import VERTC, { type IRTCEngine } from '@volcengine/rtc';
import type { InterviewSession } from '../../types/domain';

export class InterviewRtcClient {
  private engine?: IRTCEngine;
  private recognition?: SpeechRecognitionLike;
  private keepRecognizing = false;

  async join(session: InterviewSession, onTranscript: (text: string) => void) {
    const permission = await VERTC.enableDevices({ audio: true, video: false });
    if (!permission.audio) throw new Error('请允许浏览器使用麦克风');
    const engine = VERTC.createEngine(session.appId);
    engine.on(VERTC.events.onError, (payload) => console.error('VeRTC error', payload));
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
    await engine.startAudioCapture();
    return this.startTranscription(onTranscript);
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
        if (result.isFinal && text) onTranscript(text);
      }
    };
    recognition.onend = () => {
      if (!this.keepRecognizing) return;
      window.setTimeout(() => {
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
