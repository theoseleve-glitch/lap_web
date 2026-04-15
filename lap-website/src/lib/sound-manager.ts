'use client';

import { Howl, Howler } from 'howler';

class SoundManager {
  private ambient: Howl | null = null;
  private click: Howl | null = null;
  private hover: Howl | null = null;
  private _muted: boolean;
  private _initialized = false;

  constructor() {
    this._muted = typeof window !== 'undefined'
      ? localStorage.getItem('lap_sound_muted') === '1'
      : true;
  }

  init() {
    if (this._initialized) return;
    this._initialized = true;

    this.ambient = new Howl({
      src: ['/audio/ambient-hum.webm', '/audio/ambient-hum.mp3'],
      loop: true,
      volume: 0.08,
      preload: true,
    });

    this.click = new Howl({
      src: ['/audio/click.webm', '/audio/click.mp3'],
      volume: 0.15,
      preload: true,
    });

    this.hover = new Howl({
      src: ['/audio/hover.webm', '/audio/hover.mp3'],
      volume: 0.06,
      preload: true,
    });

    Howler.mute(this._muted);

    if (!this._muted) {
      this.ambient.play();
    }
  }

  playClick() {
    this.click?.play();
  }

  playHover() {
    this.hover?.play();
  }

  startAmbient() {
    if (!this._muted && this.ambient && !this.ambient.playing()) {
      this.ambient.play();
    }
  }

  get muted() {
    return this._muted;
  }

  toggleMute() {
    this._muted = !this._muted;
    Howler.mute(this._muted);
    localStorage.setItem('lap_sound_muted', this._muted ? '1' : '0');

    if (this._muted) {
      this.ambient?.pause();
    } else {
      this.startAmbient();
    }

    return this._muted;
  }
}

export const soundManager = new SoundManager();
