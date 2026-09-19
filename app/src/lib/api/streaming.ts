import { apiClient } from '@/lib/api/client';
import type { GenerationRequest } from '@/lib/api/types';

export interface StreamingGenerateCallbacks {
  onStarted?: (generationId: string) => void;
  onStatus?: (status: 'loading_model' | 'generating') => void;
  onFirstAudio?: () => void;
}

export interface StreamingGenerateResult {
  generationId: string;
  duration: number;
}

/**
 * WebSocket streaming generation (W3): audio chunks play live via Web Audio
 * as the engine generates them. The generation is persisted server-side —
 * "done" resolves with the id so the normal history/SSE flow takes over.
 *
 * Throws on error only when no audio has arrived yet; callers use that to
 * fall back to REST without regenerating over already-played audio.
 */
class StreamingGenerateClient {
  private audioCtx: AudioContext | null = null;
  private nextStartTime = 0;

  async generate(
    request: GenerationRequest,
    callbacks: StreamingGenerateCallbacks = {},
  ): Promise<StreamingGenerateResult> {
    const wsUrl = apiClient.getWsUrl('/generate/stream-ws');
    const ws = new WebSocket(wsUrl);

    return new Promise<StreamingGenerateResult>((resolve, reject) => {
      let gotAudio = false;
      let settled = false;

      const fail = (message: string) => {
        if (settled) return;
        settled = true;
        try {
          ws.close();
        } catch {
          // already closing
        }
        reject(new Error(message));
      };

      ws.onopen = () => {
        ws.send(JSON.stringify(request));
      };

      ws.onmessage = (event) => {
        let msg: {
          type: string;
          generation_id?: string;
          status?: string;
          data?: string;
          sample_rate?: number;
          duration?: number;
          message?: string;
        };
        try {
          msg = JSON.parse(event.data as string);
        } catch {
          return; // heartbeats etc.
        }

        if (msg.type === 'started' && msg.generation_id) {
          callbacks.onStarted?.(msg.generation_id);
        } else if (msg.type === 'status' && (msg.status === 'loading_model' || msg.status === 'generating')) {
          callbacks.onStatus?.(msg.status);
        } else if (msg.type === 'audio' && msg.data) {
          if (!gotAudio) {
            gotAudio = true;
            callbacks.onFirstAudio?.();
          }
          try {
            this.playChunk(msg.data, msg.sample_rate ?? 24000);
          } catch (error) {
            console.error('Failed to play streamed chunk:', error);
          }
        } else if (msg.type === 'done' && msg.generation_id) {
          settled = true;
          try {
            ws.close();
          } catch {
            // already closing
          }
          resolve({
            generationId: msg.generation_id,
            duration: msg.duration ?? 0,
          });
        } else if (msg.type === 'error') {
          if (gotAudio) {
            // Audio already played — report but don't trigger a REST
            // re-generation that would double-play.
            console.error('Streamed generation failed mid-stream:', msg.message);
            settled = true;
            reject(new Error(msg.message ?? 'Stream failed'));
          } else {
            fail(msg.message ?? 'Stream failed');
          }
        }
      };

      ws.onerror = () => {
        fail('WebSocket connection failed');
      };

      ws.onclose = () => {
        fail('Connection closed before generation completed');
      };
    });
  }

  /** Decode a base64 float32 PCM chunk and schedule sequential playback. */
  private playChunk(base64Data: string, sampleRate: number) {
    if (!this.audioCtx) {
      this.audioCtx = new AudioContext();
    }
    const ctx = this.audioCtx;
    if (ctx.state === 'suspended') {
      void ctx.resume();
    }

    const bin = atob(base64Data);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) {
      bytes[i] = bin.charCodeAt(i);
    }
    const samples = new Float32Array(bytes.buffer);

    const buffer = ctx.createBuffer(1, samples.length, sampleRate);
    buffer.copyToChannel(samples, 0);

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    const startAt = Math.max(ctx.currentTime, this.nextStartTime);
    source.start(startAt);
    this.nextStartTime = startAt + buffer.duration;
  }

  stopPlayback() {
    this.nextStartTime = 0;
    if (this.audioCtx) {
      void this.audioCtx.close();
      this.audioCtx = null;
    }
  }
}

export const streamingGenerateClient = new StreamingGenerateClient();
