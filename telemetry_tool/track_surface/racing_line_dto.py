from __future__ import annotations

def racing_line_from_solution(sol, condition: str) -> dict:
    d, n, v = sol.distance_m, sol.lateral_offset_m, sol.speed_mps
    points = [{"d": float(d[i]), "n": float(n[i]), "v": float(v[i])} for i in range(len(d))]
    return {
        "points": points,
        "condition": condition,
        "solver_meta": {
            "status": str(sol.solver_status),
            "solve_time_s": float(sol.solver_time_s),
            "lap_time_s": float(sol.optimal_lap_time_s),
        },
    }
