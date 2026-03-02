import type { AnalyzerState, AnalyzerAction, ChartType } from './types';

export const initialAnalyzerState: AnalyzerState = {
  playing: false,
  currentDistance: 0,
  playbackSpeed: 1,
  primaryLap: 1,
  overlayLap: null,
  activeSection: 'full',
  visibleCharts: ['speed', 'g-lat', 'brake-throttle', 'steering'],
};

export function analyzerReducer(state: AnalyzerState, action: AnalyzerAction): AnalyzerState {
  switch (action.type) {
    case 'TOGGLE_PLAY':
      return { ...state, playing: !state.playing };

    case 'SET_DISTANCE':
      return { ...state, currentDistance: action.distance };

    case 'SET_SPEED':
      return { ...state, playbackSpeed: action.speed };

    case 'SET_LAP':
      return { ...state, primaryLap: action.lap, currentDistance: 0, playing: false };

    case 'SET_OVERLAY_LAP':
      return { ...state, overlayLap: action.lap };

    case 'SET_SECTION':
      return { ...state, activeSection: action.section, currentDistance: 0, playing: false };

    case 'TOGGLE_CHART': {
      const charts = state.visibleCharts;
      const has = charts.includes(action.chart);
      return {
        ...state,
        visibleCharts: has
          ? charts.filter((c: ChartType) => c !== action.chart)
          : [...charts, action.chart],
      };
    }

    case 'RESET':
      return { ...initialAnalyzerState };

    default:
      return state;
  }
}
