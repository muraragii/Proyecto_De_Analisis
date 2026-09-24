"""Genera los CSV/Excel de ejemplo en /samples para probar la app a mano.

Uso (desde apps/api):  .venv\\Scripts\\python scripts\\export_samples.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import samples  # noqa: E402

OUT = Path(__file__).resolve().parents[3] / "samples"

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    samples.ecommerce().to_csv(OUT / "ecommerce_pedidos.csv", index=False)
    samples.restaurante().to_csv(OUT / "restaurante_tickets.csv", index=False, sep=";")
    samples.clinica().to_excel(OUT / "clinica_citas.xlsx", index=False)
    print(f"Ejemplos generados en {OUT}")
