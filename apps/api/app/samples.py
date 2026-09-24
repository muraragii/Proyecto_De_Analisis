"""Datasets sintéticos por industria: para tests, demos y onboarding ("probar con datos de ejemplo")."""

import numpy as np
import pandas as pd


def ecommerce(n: int = 500, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    productos = {"Camiseta": 250, "Pantalón": 600, "Tenis": 1200, "Gorra": 180,
                 "Chamarra": 1500, "Calcetines": 90, "Mochila": 800}
    categorias = {"Camiseta": "Ropa", "Pantalón": "Ropa", "Chamarra": "Ropa",
                  "Tenis": "Calzado", "Calcetines": "Calzado", "Gorra": "Accesorios",
                  "Mochila": "Accesorios"}
    producto = rng.choice(list(productos), n)
    cantidad = rng.integers(1, 5, n)
    return pd.DataFrame({
        "id_pedido": np.arange(1000, 1000 + n),
        "fecha_pedido": pd.to_datetime("2025-01-01")
        + pd.to_timedelta(rng.integers(0, 365, n), unit="D"),
        "producto": producto,
        "categoría": [categorias[p] for p in producto],
        "cantidad": cantidad,
        "total_venta": [productos[p] * q for p, q in zip(producto, cantidad)],
        "canal": rng.choice(["Web", "App", "Marketplace"], n, p=[0.5, 0.3, 0.2]),
        "estado": rng.choice(["Entregado", "Enviado", "Cancelado"], n, p=[0.8, 0.15, 0.05]),
        "ciudad": rng.choice(["CDMX", "Guadalajara", "Monterrey", "Puebla"], n),
    })


def restaurante(n: int = 800, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dias = pd.to_datetime("2025-03-01") + pd.to_timedelta(rng.integers(0, 90, n), unit="D")
    horas = rng.choice([13, 14, 15, 19, 20, 21, 22], n, p=[0.1, 0.2, 0.15, 0.1, 0.2, 0.15, 0.1])
    return pd.DataFrame({
        "ticket": np.arange(1, n + 1),
        "fecha": (dias + pd.to_timedelta(horas, unit="h")
                  + pd.to_timedelta(rng.integers(0, 60, n), unit="m")).strftime("%d/%m/%Y %H:%M"),
        "mesa": rng.integers(1, 20, n),
        "mesero": rng.choice(["Ana", "Luis", "Carla", "Jorge"], n),
        "platillo": rng.choice(["Tacos", "Enchiladas", "Pozole", "Mole", "Chilaquiles"], n),
        "comensales": rng.integers(1, 7, n),
        "total": [f"${v:,.2f}" for v in rng.normal(450, 120, n).clip(80)],
    })


def restaurante_pos(n_tickets: int = 400, seed: int = 3) -> pd.DataFrame:
    """Exportación "real" de un punto de venta: una fila por platillo (varias por ticket),
    precio unitario + cantidad, fechas dd/mm/aaaa como texto, un valor mal capturado y la
    fila TOTAL que agregan los Excel. Sirve para ver las advertencias de calidad."""
    rng = np.random.default_rng(seed)
    menu = {"Tacos al pastor": 25, "Quesadilla": 45, "Pozole": 120, "Enchiladas": 110,
            "Agua de horchata": 35, "Refresco": 30, "Cerveza": 55, "Flan": 50}
    start = pd.Timestamp("2025-04-02")  # miércoles: la primera semana queda incompleta
    rows = []
    for t in range(1, n_tickets + 1):
        day = start + pd.Timedelta(days=int(rng.integers(0, 60)))
        hour = int(rng.choice([13, 14, 15, 19, 20, 21], p=[0.15, 0.25, 0.15, 0.1, 0.2, 0.15]))
        when = day + pd.Timedelta(hours=hour, minutes=int(rng.integers(0, 60)))
        mesero = rng.choice(["Ana", "Luis", "Carla", "Jorge"])
        for item in rng.choice(list(menu), int(rng.integers(1, 5)), replace=False):
            qty = int(rng.integers(1, 4))
            rows.append({
                "No. Ticket": t,
                "Fecha": when.strftime("%d/%m/%Y %H:%M"),
                "Mesero": mesero,
                "Platillo": item,
                "Cantidad": qty,
                "Precio unitario": menu[item],
                "Importe": f"${menu[item] * qty:,.2f}",
            })
    df = pd.DataFrame(rows)
    df.loc[7, "Importe"] = "pendiente"
    total = pd.to_numeric(df["Importe"].str.replace(r"[$,]", "", regex=True), errors="coerce").sum()
    df.loc[len(df)] = {"No. Ticket": None, "Fecha": None, "Mesero": None, "Platillo": "TOTAL",
                       "Cantidad": None, "Precio unitario": None, "Importe": f"${total:,.2f}"}
    return df


def clinica(n: int = 600, seed: int = 2) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    especialidades = {"Dra. López": "Pediatría", "Dr. Pérez": "Cardiología",
                      "Dra. Ruiz": "Dermatología", "Dr. Gómez": "Medicina general"}
    medico = rng.choice(list(especialidades), n)
    inicio = pd.to_datetime("2025-06-02 08:00")
    return pd.DataFrame({
        "id_cita": [f"C-{i:05d}" for i in range(n)],
        "fecha_cita": inicio + pd.to_timedelta(rng.integers(0, 120, n), unit="D")
        + pd.to_timedelta(rng.integers(0, 10, n), unit="h"),
        "médico": medico,
        "especialidad": [especialidades[m] for m in medico],
        "paciente": [f"Paciente {i}" for i in rng.integers(1, 300, n)],
        "estado": rng.choice(["Asistió", "Canceló", "No asistió"], n, p=[0.75, 0.15, 0.1]),
        "costo": rng.choice([500, 800, 1200], n),
        "aseguradora": rng.choice(["Particular", "GNP", "AXA", "MetLife"], n),
    })
