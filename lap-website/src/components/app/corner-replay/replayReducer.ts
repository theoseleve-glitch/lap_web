import type { ReplayState, ReplayAction, PlaybackSpeed } from '@/types/corner-replay';

const SPEEDS: PlaybackSpeed[] = [0.25, 0.5, 1, 2];

export const initialReplayState: ReplayState = {
  mode: 'review',
  cornerIndex: 0,
  lapA: 1,
  lapB: 2,
  frame: 0,
  playing: false,
  speed: 1,
};

export function replayReducer(state: ReplayState, action: ReplayAction): ReplayState {
  switch (action.type) {
    case 'SET_MODE':
      return { ...state, mode: action.mode, frame: 0, playing: false };
    case 'SET_CORNER':
      return { ...state, cornerIndex: action.index, frame: 0, playing: false };
    case 'NEXT_CORNER':
      return {
        ...state,
        cornerIndex: (state.cornerIndex + 1) % action.total,
        frame: 0,
        playing: false,
      };
    case 'PREV_CORNER':
      return {
        ...state,
        cornerIndex: (state.cornerIndex - 1 + action.total) % action.total,
        frame: 0,
        playing: false,
      };
    case 'SET_LAP_A':
      return { ...state, lapA: action.lap, frame: 0, playing: false };
    case 'SET_LAP_B':
      return { ...state, lapB: action.lap, frame: 0, playing: false };
    case 'SET_FRAME':
      return { ...state, frame: action.frame };
    case 'TOGGLE_PLAY':
      return { ...state, playing: !state.playing };
    case 'SET_SPEED':
      return { ...state, speed: action.speed };
    default:
      return state;
  }
}
