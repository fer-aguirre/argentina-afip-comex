"""Parámetros de una consulta y nombre del archivo exportado.

`Consulta` guarda la búsqueda una sola vez: la usan tanto `query_data` (para
filtrar) como `export_query_result` (para nombrar el archivo), así el nombre
siempre describe los datos que contiene. Valida y normaliza los valores al
crearse.

Formato del nombre exportado (las partes vacías se omiten):

    <país>_<régimen>_<nombre>_<códigos>_<años>_<AAAAMMDDTHHMMSS>.<formato>
    ej. ar_importacion_acme_2701_2019-2021+2024_20261111T153012.csv

Este módulo tiene la misma estructura en argentina_afip_comex y
uruguay_dua_comex. Solo cambia lo propio de cada país: `COUNTRY_PREFIX` y el
régimen (fijo en Argentina, que solo publica importaciones; elegible en
Uruguay con `tipo_regimen`).
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

# --- Propio de cada país ---
# Prefijo al inicio de cada archivo exportado.
COUNTRY_PREFIX = "ar"
# El dataset de ARCA solo tiene importaciones, así que el régimen es fijo.
REGIMEN_LABEL = "importacion"

# --- Común a ambos proyectos ---
# Largo máximo de la parte del nombre de importador en el archivo.
MAX_NOMBRE_CHARS = 40
# Cantidad máxima de códigos NCM que se escriben en el archivo; el resto se
# resume como "-y<N>mas".
MAX_CODES_IN_NAME = 3
# Fecha y hora de exportación en formato básico ISO 8601 (ej. 20261111T153012).
# No usa "_" ni "-", que ya separan las partes del nombre y los rangos de años.
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S"

# Matches any character that isn't a digit, to strip separators from an NCM code.
NCM_NON_DIGIT_PATTERN = re.compile(r"\D+")
# Runs of characters that aren't safe in a filename on every OS.
UNSAFE_CHARS_PATTERN = re.compile(r"[^a-z0-9.-]+")


def normalize_ncm(code: str) -> str:
    """Strip separators from an NCM code or prefix.

    People write NCM codes with dots (e.g. "84.20" or "8420.10.00") or without
    (e.g. "8420"). Stripping non-digit characters makes all forms equivalent.

    Args:
        code: NCM code or prefix, with or without separators.

    Returns:
        The code with any non-digit characters removed.
    """
    return NCM_NON_DIGIT_PATTERN.sub("", code)


def _slug(text: str) -> str:
    """Turn free text into a filename-safe part.

    Removes accents, lowercases, replaces every run of unsafe characters
    (spaces, "/", ":", tabs, etc.) with a single "_" and trims "_" and "."
    from the ends, so the part can't create folders or hidden files.

    Args:
        text: Text to convert, e.g. an importer name.

    Returns:
        The filename-safe text, e.g. "Café del Sur S.A." -> "cafe_del_sur_s.a".
    """
    ascii_text = (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    )
    return UNSAFE_CHARS_PATTERN.sub("_", ascii_text.lower()).strip("_.")


def _years_label(years: tuple[int, ...]) -> str:
    """Describe sorted years, collapsing consecutive ones into ranges.

    Args:
        years: Sorted, unique years.

    Returns:
        E.g. (2024,) -> "2024"; (2019, 2020, 2021, 2024) -> "2019-2021+2024".
    """
    groups: list[list[int]] = []
    for year in years:
        # Extend the current group if this year follows it, else start a new one.
        if groups and year == groups[-1][-1] + 1:
            groups[-1].append(year)
        else:
            groups.append([year])
    return "+".join(
        str(group[0]) if len(group) == 1 else f"{group[0]}-{group[-1]}"
        for group in groups
    )


def _codes_label(codes: tuple[str, ...]) -> str:
    """Describe NCM codes, listing at most MAX_CODES_IN_NAME of them.

    Args:
        codes: Sorted, unique, digit-only NCM codes.

    Returns:
        E.g. ("2701", "2702") -> "2701-2702";
        ("01", "02", "03", "04", "05") -> "01-02-03-y2mas".
    """
    label = "-".join(codes[:MAX_CODES_IN_NAME])
    extra = len(codes) - MAX_CODES_IN_NAME
    return f"{label}-y{extra}mas" if extra > 0 else label


@dataclass(frozen=True)
class Consulta:
    """Parámetros de una búsqueda en el dataset.

    Se pasan los valores tal como los escribe el usuario (`years`, `nombre`,
    `codigo`) y al crearse se validan y normalizan en los campos `*_values`,
    que son los que usan la consulta y el nombre del archivo.

    Attributes:
        years: Año o lista de años a consultar.
        nombre: Nombre (o parte del nombre) del importador. Se busca como
            texto literal y no distingue mayúsculas/minúsculas. Cuanto más
            específico, mejor: un término corto (ej. "sa") puede devolver
            miles de coincidencias distintas.
        codigo: Código NCM o lista de códigos/prefijos. Los puntos u otros
            separadores son opcionales (ej. "84.20" equivale a "8420").
        year_values: Años ordenados y sin duplicados.
        nombre_value: `nombre` sin espacios al inicio ni al final.
        codigo_values: Códigos solo con dígitos, ordenados y sin duplicados
            (vacío si no se indicó `codigo`).

    Raises:
        ValueError: Si no hay años, si `nombre` está vacío, si algún código
            no tiene dígitos, o si no se indica ni `nombre` ni `codigo`.
    """

    years: int | Sequence[int]
    nombre: str | None = None
    codigo: str | Sequence[str] | None = None
    year_values: tuple[int, ...] = field(init=False, repr=False, compare=False)
    nombre_value: str | None = field(init=False, repr=False, compare=False)
    codigo_values: tuple[str, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate the inputs and fill the normalized `*_values` fields."""
        year_values = tuple(
            sorted({self.years} if isinstance(self.years, int) else set(self.years))
        )
        if not year_values:
            raise ValueError("Debe indicar al menos un año.")

        nombre_value = None
        if self.nombre is not None:
            nombre_value = self.nombre.strip()
            # Un nombre vacío coincidiría con todas las filas.
            if not nombre_value:
                raise ValueError("`nombre` está vacío.")

        codigo_values: tuple[str, ...] = ()
        if self.codigo is not None:
            raw_codes = [self.codigo] if isinstance(self.codigo, str) else self.codigo
            if not raw_codes:
                raise ValueError("`codigo` está vacío.")
            for code in raw_codes:
                # Un código sin dígitos coincidiría con todas las filas.
                if not normalize_ncm(code):
                    raise ValueError(
                        f"Código NCM inválido: {code!r}. Debe tener al menos un dígito."
                    )
            codigo_values = tuple(sorted({normalize_ncm(code) for code in raw_codes}))

        if nombre_value is None and not codigo_values:
            raise ValueError("Debe indicar al menos `nombre` o `codigo`.")

        # Frozen dataclass: los campos derivados se asignan con object.__setattr__.
        object.__setattr__(self, "year_values", year_values)
        object.__setattr__(self, "nombre_value", nombre_value)
        object.__setattr__(self, "codigo_values", codigo_values)

    def export_filename(self, formato: str) -> str:
        """Arma el nombre del archivo exportado para esta consulta.

        Incluye la fecha y hora actual (hasta segundos) para que exports
        repetidos no se pisen. Ver el formato en la docstring del módulo.

        Args:
            formato: Extensión del archivo ("csv", "xlsx" o "parquet").

        Returns:
            Nombre de archivo sin carpeta, seguro en cualquier sistema.
        """
        parts = [COUNTRY_PREFIX, REGIMEN_LABEL]
        if self.nombre_value is not None:
            # Si el nombre queda vacío al limpiarlo (ej. "???"), se omite.
            nombre_part = _slug(self.nombre_value)[:MAX_NOMBRE_CHARS].rstrip("_.-")
            if nombre_part:
                parts.append(nombre_part)
        if self.codigo_values:
            parts.append(_codes_label(self.codigo_values))
        parts.append(_years_label(self.year_values))
        # Hora local de quien exporta.
        parts.append(datetime.now().astimezone().strftime(TIMESTAMP_FORMAT))
        return f"{'_'.join(parts)}.{formato}"
