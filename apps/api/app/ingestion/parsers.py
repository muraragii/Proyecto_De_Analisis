"""Lectura de archivos subidos (CSV / Excel) a DataFrame."""

import csv
import io
import re
from pathlib import PurePath

import pandas as pd

SUPPORTED_EXTENSIONS = {".csv", ".txt", ".xlsx", ".xls"}
# cp1252: la de los CSV que exporta Excel en Windows (comillas tipográficas, €, ñ).
# latin-1 al final: nunca falla, pero confunde esos caracteres.
CSV_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


class UnsupportedFileError(ValueError):
    pass


def file_extension(filename: str) -> str:
    return PurePath(filename).suffix.lower()


def read_table(content: bytes, filename: str) -> pd.DataFrame:
    ext = file_extension(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(f"Formato no soportado: '{ext}'. Usa CSV o Excel.")

    sheet_info: dict = {}
    if ext in {".xlsx", ".xls"}:
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, engine=_excel_engine())
        df, sheet_info = _combine_sheets(sheets)
    else:
        df = _read_csv(content)

    df = _clean(df)
    df.attrs.update(sheet_info)
    return df


def _excel_engine() -> str | None:
    try:
        import python_calamine  # noqa: F401  (varias veces más rápido que openpyxl)
        return "calamine"
    except ImportError:
        return None


def _combine_sheets(sheets: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    """Excel con varias hojas: si todas tienen las mismas columnas (p. ej. una hoja por
    año) se combinan; si no, se usa la primera y se avisa cuáles quedaron fuera."""
    filled = {name: df for name, df in sheets.items() if not df.dropna(how="all").empty}
    if len(filled) <= 1:
        return next(iter(filled.values()), next(iter(sheets.values()))), {}
    names = list(filled)
    columns = [[str(c).strip().lower() for c in df.columns] for df in filled.values()]
    if all(c == columns[0] for c in columns):
        frames = [df.set_axis(filled[names[0]].columns, axis=1) for df in filled.values()]
        return pd.concat(frames, ignore_index=True), {"sheets_combined": names}
    return filled[names[0]], {"sheets_used": names[0], "sheets_ignored": names[1:]}


def _read_csv(content: bytes) -> pd.DataFrame:
    for encoding in CSV_ENCODINGS:
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        return pd.read_csv(io.StringIO(text), sep=_sniff_delimiter(text))
    raise UnsupportedFileError("No se pudo detectar la codificación del CSV.")


def _sniff_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:50])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df.columns = [_column_name(c, i) for i, c in enumerate(df.columns)]
    df, summary_rows = _drop_summary_rows(df)
    df = df.reset_index(drop=True)
    # El perfilado lo reporta como advertencia (df.attrs viaja con el DataFrame).
    df.attrs["summary_rows"] = summary_rows
    return df


_NUMBER_LIKE = re.compile(r"[\s$€£-]*[\d.,]+\s*%?")
_SUMMARY_LABELS = {"total", "totales", "gran total", "total general", "subtotal", "suma",
                   "grand total", "sum", "totals"}


def _drop_summary_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Quita filas tipo "TOTAL" que los Excel suelen traer al final: sumarlas de nuevo
    duplicaría las cifras. Una fila es de resumen si alguna celda de texto dice "total"
    (o similar) y el resto de celdas de texto están vacías."""
    text_cols = [c for c in df.columns if df[c].dtype == object or pd.api.types.is_string_dtype(df[c])]
    if not text_cols:
        return df, []
    text = df[text_cols].apply(lambda s: s.astype("string").str.strip().str.lower().str.rstrip(":"))
    is_label = text.isin(_SUMMARY_LABELS)
    has_label = is_label.any(axis=1)
    # Los montos escritos como texto ("$12,345.00") no cuentan como descripción.
    is_number = text.apply(lambda s: s.str.fullmatch(_NUMBER_LIKE).fillna(False))
    other_text = (text.notna() & (text != "") & ~is_label & ~is_number).sum(axis=1)
    mask = has_label & (other_text == 0)
    # Una etiqueta por fila eliminada: la celda que dice "total".
    labels = (
        df.loc[mask, text_cols].where(is_label[mask]).bfill(axis=1).iloc[:, 0]
        .astype(str).str.strip().tolist()
    )
    return df.loc[~mask], labels


def _column_name(name: object, index: int) -> str:
    text = str(name).strip()
    if not text or text.startswith("Unnamed:"):
        return f"columna_{index + 1}"
    return text
