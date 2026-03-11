"""Brake point landmark description templates."""
from __future__ import annotations

# Templates for describing brake points relative to landmarks
# Keys: (corner_type, vehicle_class)
# Values: template string with {distance_m}, {speed_kmh}, {landmark} placeholders

REFERENCE_POINT_TEMPLATES: dict[str, str] = {
    "standard": "Brake at the {distance_m:.0f}m board (or {landmark}). You should be travelling at approximately {speed_kmh:.0f} km/h when you hit the pedal.",
    "late_brake": "Your current brake point is about {delta_m:.0f}m early. Move it to {landmark} — that's {target_m:.0f}m from corner entry. Trust the brakes.",
    "early_brake": "You're braking {delta_m:.0f}m past the optimal point. Move your marker back to {landmark}. Better to brake a touch early and trail in than to arrive too hot.",
    "no_marker": "Pick a fixed reference point at {distance_m:.0f}m from the corner: a crack in the tarmac, a marshal post, a kerb change, a shadow line. Use it every lap.",
    "kart_specific": "On a kart, brake points are much closer to the corner — {distance_m:.0f}m is typical. Look for the painted kerb start or the nearest cone.",
    "car_specific": "At {speed_kmh:.0f} km/h, you need approximately {distance_m:.0f}m of braking. Find a marker board, tree line, or barrier joint at that distance.",
}
