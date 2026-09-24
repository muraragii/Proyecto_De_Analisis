import re
import unicodedata


def normalize(text: str) -> str:
    """Minúsculas y sin acentos: 'Categoría' -> 'categoria'."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def name_tokens(name: str) -> list[str]:
    """Separa un nombre de columna en palabras: 'FechaPedido_v2' -> ['fecha', 'pedido', 'v2']."""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(name))
    return [t for t in re.split(r"[^a-z0-9]+", normalize(spaced)) if t]
