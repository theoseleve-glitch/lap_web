import numpy as np
from telemetry_tool.track_surface.racing_line_dto import racing_line_from_solution
from telemetry_tool.lap_oracle.config import OCPSolution

def test_dto_zips_arrays_and_carries_meta():
    sol = OCPSolution(distance_m=np.array([0.0, 5.0]), lateral_offset_m=np.array([0.1, -0.2]),
                      speed_mps=np.array([30.0, 28.0]), solver_status="solved",
                      solver_time_s=4.2, optimal_lap_time_s=88.1)
    out = racing_line_from_solution(sol, condition="dry")
    assert out["condition"] == "dry"
    assert out["points"] == [{"d":0.0,"n":0.1,"v":30.0},{"d":5.0,"n":-0.2,"v":28.0}]
    assert out["solver_meta"] == {"status":"solved","solve_time_s":4.2,"lap_time_s":88.1}
