"""Lectura de archivos subidos (CSV / Excel) a DataFrame."""

import csv
import io
from pathlib import PurePath

import pandas as pd

SUPPORTED_EXTENSIONS = {".csv", ".txt", ".xlsx", ".xls"}
CSV_ENCODINGS = ("utf-8-sig", "latin-1")


class UnsupportedFileError(ValueError):
    pass


def file_extension(filename: str) -> str:
    return PurePath(filename).suffix.lower()


def read_table(content: bytes, filename: str) -> pd.DataFrame:
    ext = file_extension(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(f"Formato no soportado: '{ext}'. Usa CSV o Excel.")

    if ext in {".xlsx", ".xls"}:
        # Primera hoja; la selección de hoja llega en una fase posterior.
        df = pd.read_excel(io.BytesIO(content), sheet_name=0)
    else:
        df = _read_csv(content)

    return _clean(df)


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
    return df.reset_index(drop=True)


def _column_name(name: object, index: int) -> str:
    text = str(name).strip()
    if not text or text.startswith("Unnamed:"):
        return f"columna_{index + 1}"
    return text
