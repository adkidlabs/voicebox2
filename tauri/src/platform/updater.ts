import type { PlatformUpdater, UpdateStatus } from '@/platform/types';

// Custom build: auto-updates are intentionally disabled (W5 de-networking).
// This no-op never touches the network — the Rust-side updater plugin has
// been removed, so any plugin call would reject anyway.

class TauriUpdater implements PlatformUpdater {
  private status: UpdateStatus = {
    checking: false,
    available: false,
    downloading: false,
    installing: false,
    readyToInstall: false,
  };

  private subscribers: Set<(status: UpdateStatus) => void> = new Set();

  subscribe(callback: (status: UpdateStatus) => void): () => void {
    this.subscribers.add(callback);
    callback(this.status);
    return () => {
      this.subscribers.delete(callback);
    };
  }

  getStatus(): UpdateStatus {
    return { ...this.status };
  }

  async checkForUpdates(): Promise<void> {
    // No-op — updates are disabled in this build.
  }

  async downloadAndInstall(): Promise<void> {
    // No-op — updates are disabled in this build.
  }

  async restartAndInstall(): Promise<void> {
    // No-op — updates are disabled in this build.
  }
}

export const tauriUpdater = new TauriUpdater();
