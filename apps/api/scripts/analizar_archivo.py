r"""Pasa un archivo por todo el pipeline (lectura, perfilado, gráficos y hallazgos) y
muestra resultados y tiempos. Útil para probar datos reales sin usar la web.

Uso (desde apps/api):
    .venv\Scripts\python scripts\analizar_archivo.py ruta\al\archivo.xlsx

Datos públicos grandes para probar (guárdalos en data-externa/, ignorada por Git):
    Online Retail II (UCI, 1 M de filas de una tienda en línea):
    https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from app.ingestion.parsers import read_table  # noqa: E402
from app.insights import generate_insights  # noqa: E402
from app.profiling import profile_dataframe  # noqa: E402
from app.recommender import chart_data, recommend  # noqa: E402


def main(path: Path) -> None:
    t = time.perf_counter()
    df = read_table(path.read_bytes(), path.name)
    print(f"Lectura: {time.perf_counter() - t:.1f}s · {len(df):,} filas · {len(df.columns)} columnas")

    t = time.perf_counter()
    profile, coerced = profile_dataframe(df)
    print(f"Perfilado: {time.perf_counter() - t:.1f}s\n\nColumnas:")
    for c in profile.columns:
        summary = "se suma" if c.additive else "se promedia" if c.additive is False else ""
        print(f"  {c.name!r}: {c.semantic_type} {summary} · vacíos {c.null_ratio:.0%} · "
              f"{c.n_unique:,} valores distintos")

    print("\nCalidad de los datos:")
    for w in profile.warnings:
        print(f"  [{w.level}] {w.message}")

    rec = recommend(profile)
    print(f"\nIndustria: {rec.industry or 'genérica'} (confianza {rec.detection_confidence})")
    t = time.perf_counter()
    for spec in rec.charts:
        data = chart_data(coerced, spec)
        preview = data.get("value", [(p["x"], p["y"]) for p in data.get("points", [])][:3])
        print(f"  - {spec.title}: {preview}")
        for note in data.get("notes", []):
            print(f"      nota: {note}")
    print(f"Gráficos: {time.perf_counter() - t:.1f}s")

    t = time.perf_counter()
    insights = generate_insights(profile, coerced, rec.industry)
    print(f"\nHallazgos ({time.perf_counter() - t:.1f}s):")
    for i in insights:
        print(f"  * {i.title}: {i.text}\n      ({i.basis})")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
