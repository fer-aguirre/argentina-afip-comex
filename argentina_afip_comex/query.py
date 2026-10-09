"""Consulta y exportación de declaraciones de importación de ARCA Comex.

Funciona tanto como librería (`from argentina_afip_comex.query import query_importaciones`)
como CLI (`argentina-afip-query --years 2024 --importador "acme"`). El archivo
exportado es CSV por defecto (`formato`/--formato/-f también acepta "xlsx" y
"parquet") y va por defecto al directorio actual, tanto desde la librería como
desde la CLI; usar `output_dir`/--output/-o para exportarlo a otra carpeta (que
se crea si no existe). Los notebooks pasan explícitamente
`output_dir=OUTPUTS_TABLES_DIR` para que sus exports sigan yendo a
`outputs/tables/`.

Si el dataset decodificado no existe en `data/processed/`, se descarga
automáticamente desde el release más reciente del repositorio en GitHub.
"""

import argparse
import logging
import re
from collections.abc import Sequence
from pathlib import Path

import polars as pl
import requests
from tqdm.auto import tqdm

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_TABLES_DIR = PROJECT_ROOT / "outputs" / "tables"

# Nombre fijo del archivo tal como se sube a cada GitHub release: la URL de
# "latest" necesita un nombre de archivo conocido de antemano, así que no
# incluye el rango de fechas, que crece con cada actualización.
DECODED_FILENAME = "importaciones_decoded.parquet"
DATA_PATH = PROJECT_ROOT / "data" / "processed" / DECODED_FILENAME
RELEASE_DOWNLOAD_URL = (
    "https://github.com/fer-aguirre/argentina-afip-comex/releases/latest/download/"
    + DECODED_FILENAME
)

# Formatos de archivo aceptados para exportar el resultado de una consulta.
EXPORT_FORMATS = ("csv", "xlsx", "parquet")

# Matches any character that isn't a digit, to strip separators from an NCM code.
NCM_NON_DIGIT_PATTERN = re.compile(r"\D+")


def _normalize_ncm(code: str) -> str:
    """Strip separators from an NCM code or prefix.

    NCM values in the dataset are stored with dots (e.g. "8420.10.00"), but
    people also write them without (e.g. "84201000") or with partial dots
    (e.g. "84.20"). Stripping non-digit characters from both the query and the
    column makes all these forms match the same rows.

    Args:
        code: NCM code or prefix, with or without separators.

    Returns:
        The code with any non-digit characters removed.
    """
    return NCM_NON_DIGIT_PATTERN.sub("", code)


def download_decoded_data() -> None:
    """Download the pre-built decoded dataset from the latest GitHub release.

    Downloads to a temporary file first and renames it into place only once
    complete, so an interrupted download never leaves a truncated file that
    looks like a valid cached dataset on the next run.
    """
    logger.info(
        "Dataset no encontrado localmente. Descargando desde %s...",
        RELEASE_DOWNLOAD_URL,
    )
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = DATA_PATH.with_name(f"{DATA_PATH.name}.tmp")

    response = requests.get(RELEASE_DOWNLOAD_URL, stream=True, timeout=30)
    response.raise_for_status()
    total = int(response.headers.get("content-length", 0))
    with (
        tmp_path.open("wb") as file_,
        tqdm(
            total=total, unit="B", unit_scale=True, desc="Descargando dataset"
        ) as progress,
    ):
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            file_.write(chunk)
            progress.update(len(chunk))

    tmp_path.replace(DATA_PATH)
    logger.info("Descarga completa: %s", DATA_PATH)


def query_importaciones(
    years: int | Sequence[int],
    importador: str | None = None,
    ncm: str | Sequence[str] | None = None,
) -> pl.DataFrame:
    """Consulta el dataset de importaciones reformateado.

    Agrega dos columnas derivadas de FECHA (una cadena YYYYMM): AÑO y MES.
    Si el dataset no existe localmente, se descarga primero desde el release
    más reciente en GitHub (ver RELEASE_DOWNLOAD_URL).

    Args:
        years: Año o lista de años a incluir en la consulta.
        importador: Nombre (o parte del nombre) del importador a buscar. Se
            busca como texto literal y no distingue mayúsculas/minúsculas.
            Cuanto más específico, mejor: un término corto (ej. "sa") puede
            devolver miles de coincidencias distintas.
        ncm: Código NCM o lista de códigos/prefijos a buscar. Los puntos u
            otros separadores son opcionales (ej. "84.20" equivale a "8420").

    Returns:
        DataFrame de polars con las filas que cumplen los filtros.

    Raises:
        ValueError: Si no se especifica ni `importador` ni `ncm`.
    """
    if importador is None and ncm is None:
        raise ValueError("Debe indicar al menos `importador` o `ncm`.")

    years_list = [years] if isinstance(years, int) else list(years)
    year_strs = [str(year) for year in years_list]

    filters = [pl.col("FECHA").str.slice(0, 4).is_in(year_strs)]

    if importador is not None:
        # Escapado para que caracteres como "." o "(" se busquen literalmente.
        filters.append(
            pl.col("IMPORTADOR").str.contains(f"(?i){re.escape(importador)}")
        )

    if ncm is not None:
        ncm_list = [
            _normalize_ncm(code) for code in ([ncm] if isinstance(ncm, str) else ncm)
        ]
        # La columna NCM tiene puntos ("8420.10.00"): se comparan solo los dígitos.
        ncm_digits = pl.col("NCM").str.replace_all(NCM_NON_DIGIT_PATTERN.pattern, "")
        ncm_filter = ncm_digits.str.starts_with(ncm_list[0])
        for code in ncm_list[1:]:
            ncm_filter = ncm_filter | ncm_digits.str.starts_with(code)
        filters.append(ncm_filter)

    combined_filter = filters[0]
    for extra_filter in filters[1:]:
        combined_filter = combined_filter & extra_filter

    if not DATA_PATH.exists():
        download_decoded_data()

    df_lazy = pl.scan_parquet(DATA_PATH)
    df_lazy = df_lazy.filter(combined_filter).with_columns(
        pl.col("FECHA").str.slice(0, 4).cast(pl.Int64).alias("AÑO"),
        pl.col("FECHA").str.slice(4, 2).cast(pl.Int64).alias("MES"),
    )
    return df_lazy.collect()


def export_query_result(
    df_result: pl.DataFrame,
    query_years: int | Sequence[int],
    query_importador: str | None,
    query_ncm: str | Sequence[str] | None,
    output_dir: Path | None = None,
    formato: str = "csv",
) -> Path | None:
    """Exporta el resultado de una consulta a un archivo.

    El nombre del archivo se genera dinámicamente a partir de los parámetros
    de la consulta (importador, NCM y rango de años).

    Args:
        df_result: DataFrame a exportar.
        query_years: Año o lista de años usados en la consulta.
        query_importador: Importador usado en la consulta (o None).
        query_ncm: Código(s) NCM usados en la consulta (o None).
        output_dir: Carpeta donde escribir el archivo. Si es `None`, se usa
            el directorio actual. Se crea automáticamente si no existe.
        formato: Formato de exportación: "csv" (default), "xlsx" o
            "parquet". No distingue mayúsculas/minúsculas.

    Returns:
        La ruta del archivo generado, o None si no había filas para exportar.

    Raises:
        ValueError: Si `formato` no es uno de EXPORT_FORMATS.
    """
    formato = formato.lower()
    if formato not in EXPORT_FORMATS:
        raise ValueError(
            f"formato inválido: {formato!r}. Valores válidos: {EXPORT_FORMATS}."
        )

    if df_result.height == 0:
        logger.info("La consulta no devolvió filas. No se generó ningún archivo.")
        return None

    years_list = [query_years] if isinstance(query_years, int) else list(query_years)
    start_year = min(years_list)
    end_year = max(years_list)
    year_suffix = (
        f"{start_year}-{end_year}" if start_year != end_year else str(start_year)
    )

    name_parts = []
    if query_importador:
        name_parts.append(query_importador.strip().replace(" ", "_").lower())
    if query_ncm:
        if isinstance(query_ncm, str):
            name_parts.append(_normalize_ncm(query_ncm))
        else:
            name_parts.append("-".join(_normalize_ncm(code) for code in query_ncm))

    prefix = "_".join(name_parts)
    export_dir = output_dir if output_dir is not None else Path.cwd()
    if not export_dir.exists():
        logger.info("El directorio de salida no existe, se crea: %s", export_dir)
        export_dir.mkdir(parents=True)
    export_path = export_dir / f"{prefix}_{year_suffix}.{formato}"

    logger.info("Exportando %d filas a: %s", df_result.height, export_path)
    if formato == "csv":
        df_result.write_csv(export_path)
    elif formato == "xlsx":
        df_result.write_excel(export_path)
    else:
        df_result.write_parquet(export_path)
    logger.info("Exportación completa.")
    return export_path


def _build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de la CLI `argentina-afip-query`.

    Returns:
        Parser de argparse configurado con las opciones de la consulta.
    """
    parser = argparse.ArgumentParser(
        prog="argentina-afip-query",
        description=(
            "Consulta declaraciones de importación de ARCA Comex por año, "
            "importador y/o código NCM, y exporta el resultado (CSV por "
            "defecto, o XLSX/Parquet con --formato) en el directorio actual, "
            "o en la carpeta indicada con --output. Debe indicarse "
            "--importador y/o --ncm."
        ),
    )
    parser.add_argument(
        "-y",
        "--years",
        type=int,
        nargs="+",
        required=True,
        metavar="AÑO",
        help="Uno o más años a consultar, separados por espacios (ej. --years 2023 2024 2025).",
    )
    parser.add_argument(
        "-i",
        "--importador",
        type=str,
        default=None,
        help=(
            "Nombre (o parte del nombre) del importador a buscar (texto "
            "literal, no distingue mayúsculas/minúsculas). Cuanto más "
            'específico el nombre, mejor: un término corto como "sa" puede '
            "devolver miles de coincidencias distintas."
        ),
    )
    parser.add_argument(
        "-n",
        "--ncm",
        type=str,
        nargs="+",
        default=None,
        metavar="NCM",
        help=(
            "Uno o más códigos NCM (o prefijos) a buscar, separados por espacios "
            "(ej. --ncm 73 84.20). Los puntos son opcionales (84.20 y 8420 son "
            "equivalentes)."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        metavar="RUTA",
        help=(
            "Carpeta donde escribir el archivo exportado. Por defecto es el "
            "directorio actual. Se crea automáticamente si no existe."
        ),
    )
    parser.add_argument(
        "-f",
        "--formato",
        type=str.lower,
        default="csv",
        choices=EXPORT_FORMATS,
        metavar="FORMATO",
        help="Formato de exportación: csv (default), xlsx o parquet. No distingue mayúsculas/minúsculas.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Muestra mensajes de registro detallados (nivel DEBUG) en vez de solo INFO.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada de la CLI `argentina-afip-query`.

    Args:
        argv: Argumentos de línea de comandos a parsear. Si es `None`, se
            usan los de `sys.argv`.

    Returns:
        Código de salida del proceso: 0 si la consulta se ejecutó
        correctamente, 1 si faltaron argumentos requeridos.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    if args.importador is None and args.ncm is None:
        parser.error("Debe indicar al menos --importador o --ncm.")

    df_result = query_importaciones(
        years=args.years, importador=args.importador, ncm=args.ncm
    )
    export_query_result(
        df_result,
        args.years,
        args.importador,
        args.ncm,
        output_dir=args.output,
        formato=args.formato,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
