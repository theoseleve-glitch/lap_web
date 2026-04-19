export interface ReferenceCandidate {
  session_id: string;
  driver_name: string;
  session_date: string;
  best_lap_time_s: number | null;
  best_lap_number: number | null;
  n_laps: number;
  session_type: string;
}

export interface ReferenceData {
  primary: {
    session_id: string;
    lap_number: number;
    lap_time_s: number | null;
  };
  reference: {
    session_id: string;
    lap_number: number;
    lap_time_s: number | null;
    driver_name: string;
    session_date: string;
  };
  distances: number[];
  speed: {
    primary: number[];
    reference: number[];
    delta_s: number[];
  };
  gps: {
    primary: { latitudes: number[]; longitudes: number[] };
    reference: { latitudes: number[]; longitudes: number[] };
  };
  gg: {
    primary: { accel_lat: number[]; accel_long: number[] };
    reference: { accel_lat: number[]; accel_long: number[] };
  };
}

export interface ReferenceOverlayContextValue {
  referenceSession: string | null;
  referenceLap: number | null;
  referenceData: ReferenceData | null;
  isLoading: boolean;
  error: string | null;
  setReference: (sessionId: string, lap: number) => void;
  clearReference: () => void;
}
