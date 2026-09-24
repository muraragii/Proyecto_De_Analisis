"""Combina reglas genéricas y presets de industria en una lista priorizada de gráficos."""

from pydantic import BaseModel

from app.profiling import DatasetProfile
from app.recommender.industries import INDUSTRIES, detect_industry, industry_specs
from app.recommender.rules import generic_rules
from app.recommender.schemas import ChartSpec, ChartType

MAX_CHARTS = 12
MAX_PER_TYPE = {ChartType.KPI: 4, ChartType.TABLE: 1, ChartType.SCATTER: 2, ChartType.PIE: 2}
AUTO = "auto"
GENERIC_WEIGHT_WITH_INDUSTRY = 0.8


class Recommendation(BaseModel):
    industry: str | None  # industria aplicada
    detected_industry: str | None  # la que sugiere el perfil (aunque el usuario elija otra)
    detection_confidence: float
    charts: list[ChartSpec]


def recommend(profile: DatasetProfile, industry: str | None = AUTO) -> Recommendation:
    """industry: id de industria, "auto" para detectarla, o None para solo reglas genéricas."""
    detected, confidence = detect_industry(profile)
    applied = detected if industry == AUTO else industry
    if applied is not None and applied not in INDUSTRIES:
        raise ValueError(f"Industria desconocida: {applied}")

    candidates = generic_rules(profile)
    if applied:
        # Con industria, las reglas genéricas solo completan lo que las plantillas no cubren.
        for spec in candidates:
            spec.score = round(spec.score * GENERIC_WEIGHT_WITH_INDUSTRY, 3)
        candidates = industry_specs(profile, INDUSTRIES[applied]) + candidates

    return Recommendation(
        industry=applied,
        detected_industry=detected,
        detection_confidence=confidence,
        charts=_select(candidates),
    )


def _select(candidates: list[ChartSpec]) -> list[ChartSpec]:
    # Deduplicar: si industria y reglas proponen el mismo gráfico, gana el de mayor score
    # (a igualdad, el primero, que es el de industria con título de negocio).
    best: dict[tuple, ChartSpec] = {}
    for spec in candidates:
        current = best.get(spec.key())
        if current is None or spec.score > current.score:
            best[spec.key()] = spec

    selected, per_type = [], {}
    for spec in sorted(best.values(), key=lambda s: s.score, reverse=True):
        count = per_type.get(spec.chart_type, 0)
        if count >= MAX_PER_TYPE.get(spec.chart_type, MAX_CHARTS):
            continue
        per_type[spec.chart_type] = count + 1
        selected.append(spec)
        if len(selected) == MAX_CHARTS:
            break
    return selected
