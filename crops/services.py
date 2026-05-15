from decimal import Decimal, InvalidOperation

from .models import CropProfile


def _normalized_tokens(value):
    if not value:
        return set()
    return {
        token.strip().lower()
        for token in str(value).replace("/", ",").split(",")
        if token.strip()
    }


def _decimal_or_none(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def suggest_crops(
    *,
    soil_ph=None,
    soil_classification="",
    soil_texture="",
    topography="",
    irrigation_viability="",
    average_temperature_c=None,
    annual_rainfall_mm=None,
    altitude_m=None,
    limit=3,
):
    ph_value = _decimal_or_none(soil_ph)
    temperature = _decimal_or_none(average_temperature_c)
    rainfall = _decimal_or_none(annual_rainfall_mm)
    altitude = _decimal_or_none(altitude_m)
    soil_tokens = _normalized_tokens(soil_classification) | _normalized_tokens(soil_texture)
    topography_tokens = _normalized_tokens(topography)
    irrigation_value = (irrigation_viability or "").strip().lower()

    suggestions = []

    for crop in CropProfile.objects.filter(is_active=True):
        score = 0
        reasons = []

        if ph_value is not None and crop.optimal_ph_min is not None and crop.optimal_ph_max is not None:
            if crop.optimal_ph_min <= ph_value <= crop.optimal_ph_max:
                score += 3
                reasons.append("pH is within the optimal range")
            elif abs(ph_value - crop.optimal_ph_min) <= Decimal("0.5") or abs(ph_value - crop.optimal_ph_max) <= Decimal("0.5"):
                score += 1
                reasons.append("pH is close to the optimal range")

        crop_soils = _normalized_tokens(crop.ideal_soil_types)
        if crop_soils and soil_tokens:
            overlap = crop_soils & soil_tokens
            if overlap:
                score += 4
                reasons.append(f"soil type matches {', '.join(sorted(overlap))}")

        crop_topographies = _normalized_tokens(crop.preferred_topographies)
        if crop_topographies and topography_tokens:
            overlap = crop_topographies & topography_tokens
            if overlap:
                score += 2
                reasons.append(f"terrain suits {', '.join(sorted(overlap))}")

        if altitude is not None and crop.optimal_altitude_min_m is not None and crop.optimal_altitude_max_m is not None:
            if crop.optimal_altitude_min_m <= altitude <= crop.optimal_altitude_max_m:
                score += 2
                reasons.append("altitude is suitable")

        if temperature is not None and crop.optimal_temperature_min_c is not None and crop.optimal_temperature_max_c is not None:
            if crop.optimal_temperature_min_c <= temperature <= crop.optimal_temperature_max_c:
                score += 2
                reasons.append("temperature is suitable")

        if rainfall is not None and crop.optimal_rainfall_min_mm is not None and crop.optimal_rainfall_max_mm is not None:
            if crop.optimal_rainfall_min_mm <= rainfall <= crop.optimal_rainfall_max_mm:
                score += 2
                reasons.append("rainfall is suitable")

        if irrigation_value:
            if irrigation_value == "high" and crop.irrigation_requirement in {"high", "moderate"}:
                score += 1
            elif irrigation_value == "moderate" and crop.irrigation_requirement != "high":
                score += 1
            elif irrigation_value == "not_viable" and crop.irrigation_requirement == "low":
                score += 1

        if score > 0:
            suggestions.append(
                {
                    "crop": crop,
                    "score": score,
                    "reasons": reasons or ["General agronomic fit"],
                }
            )

    suggestions.sort(key=lambda item: (-item["score"], item["crop"].name))
    return suggestions[:limit]
