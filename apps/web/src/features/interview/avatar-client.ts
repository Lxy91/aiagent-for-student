import { AvatarSDK, type AvatarSession } from '@volcengine/avatar-web-sdk';
import type { InterviewSession } from '../../types/domain';

export class InterviewAvatarClient {
  private session?: AvatarSession;
  private recognition?: SpeechRecognitionLike;
  private keepRecognizing = false;

  async start(interview: InterviewSession) {
    await this.end();
    if (!interview.avatarWssToken || !interview.avatarImageUrl) {
      throw new Error('数字人配置不完整');
    }
    const sdk = new AvatarSDK({
      wssToken: interview.avatarWssToken,
      environment: 'cn',
      logLevel: 'info',
    });
    const session = sdk.createSession({
      avatarImageUrl: interview.avatarImageUrl,
      speaker: interview.avatarSpeaker,
      userPrompt: interview.interviewPrompt,
      speechRate: -5,
      loudnessRate: 0,
      enableWebsearch: false,
      actionList: ['聆听（不说话） - 自然呼吸'],
    });
    this.session = session;
    try {
      await this.waitUntilStarted(session);
    } catch (error) {
      this.session = undefined;
      session.destroy();
      const detail = error instanceof Error ? error.message : String(error);
      if (detail.includes('WebSocket connection failed')) {
        throw new Error(
          '火山数字人服务拒绝连接。鉴权已通过，请确认账号已购买或获赠“实时互动数字人 SDK”并发额度。',
        );
      }
      throw error;
    }
  }

  private waitUntilStarted(session: AvatarSession) {
    return new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => {
        cleanup();
        reject(new Error('数字人生成超时，请稍后重试'));
      }, 90_000);
      const cleanup = () => {
        window.clearTimeout(timeout);
        session.off('start', handleStart);
        session.off('end', handleEnd);
      };
      const handleStart = () => {
        cleanup();
        resolve();
      };
      const handleEnd = (error?: Error) => {
        cleanup();
        reject(error ?? new Error('数字人会话在启动过程中结束'));
      };

      session.once('start', handleStart);
      session.once('end', handleEnd);
      void session.start().catch((error) => {
        cleanup();
        reject(error);
      });
    });
  }

  async attach(container: HTMLDivElement, onTranscript: (text: string) => void) {
    if (!this.session || this.session.state !== 'started') {
      throw new Error('数字人会话尚未启动');
    }
    this.session.setAvatarVideoCanvas(container, 'fit');
    await this.session.startAudioCapture();
    return this.startTranscription(onTranscript);
  }

  async end() {
    this.stopTranscription();
    const session = this.session;
    this.session = undefined;
    if (!session) return;
    try {
      if (session.state === 'started') await session.stopAudioCapture();
      await session.end();
    } finally {
      session.destroy();
    }
  }

  private startTranscription(onTranscript: (text: string) => void) {
    const browserWindow = window as unknown as SpeechRecognitionWindow;
    const Recognition = browserWindow.SpeechRecognition ?? browserWindow.webkitSpeechRecognition;
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
        try {
          recognition.start();
        } catch {
          // The browser may already be restarting continuous recognition.
        }
      }, 300);
    };
    this.recognition = recognition;
    this.keepRecognizing = true;
    try {
      recognition.start();
      return true;
    } catch {
      this.stopTranscription();
      return false;
    }
  }

  private stopTranscription() {
    this.keepRecognizing = false;
    const recognition = this.recognition;
    this.recognition = undefined;
    if (!recognition) return;
    recognition.onend = null;
    try {
      recognition.stop();
    } catch {
      // Recognition may already have stopped after a browser-level error.
    }
  }

}

interface SpeechRecognitionResultLike {
  isFinal: boolean;
  0?: { transcript: string };
}

interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
}

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}

interface SpeechRecognitionWindow {
  SpeechRecognition?: new () => SpeechRecognitionLike;
  webkitSpeechRecognition?: new () => SpeechRecognitionLike;
}
