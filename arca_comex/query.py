"""Consulta y exportación de declaraciones de importación de ARCA Comex.

Funciona tanto como librería (`from arca_comex.query import query_importaciones`)
como CLI (`arca-comex-query --years 2024 --importador "acme"`).
"""

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = (
    PROJECT_ROOT / "data" / "processed" / "importaciones_2019-2026_decoded.parquet"
)
EXPORT_DIR = PROJECT_ROOT / "outputs" / "tables"


def query_importaciones(
    years: int | Sequence[int],
    importador: str | None = None,
    ncm: str | Sequence[str] | None = None,
) -> pl.DataFrame:
    """Consulta el dataset de importaciones reformateado.

    Agrega dos columnas derivadas de FECHA (una cadena YYYYMM): AÑO y MES.

    Args:
        years: Año o lista de años a incluir en la consulta.
        importador: Nombre (o parte del nombre) del importador a buscar.
            La búsqueda no distingue mayúsculas/minúsculas.
        ncm: Código NCM o lista de códigos/prefijos a buscar.

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
        filters.append(pl.col("IMPORTADOR").str.contains(f"(?i){importador}"))

    if ncm is not None:
        ncm_list = [ncm] if isinstance(ncm, str) else list(ncm)
        ncm_filter = pl.col("NCM").str.starts_with(ncm_list[0])
        for code in ncm_list[1:]:
            ncm_filter = ncm_filter | pl.col("NCM").str.starts_with(code)
        filters.append(ncm_filter)

    combined_filter = filters[0]
    for extra_filter in filters[1:]:
        combined_filter = combined_filter & extra_filter

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
) -> Path | None:
    """Exporta el resultado de una consulta a un archivo Excel.

    El nombre del archivo se genera dinámicamente a partir de los parámetros
    de la consulta (importador, NCM y rango de años).

    Args:
        df_result: DataFrame a exportar.
        query_years: Año o lista de años usados en la consulta.
        query_importador: Importador usado en la consulta (o None).
        query_ncm: Código(s) NCM usados en la consulta (o None).

    Returns:
        La ruta del archivo Excel generado, o None si no había filas para exportar.
    """
    if df_result.height == 0:
        logger.info("La consulta no devolvió filas. No se generó ningún archivo Excel.")
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
            name_parts.append(query_ncm)
        else:
            name_parts.append("-".join(query_ncm))

    prefix = "_".join(name_parts)
    export_path = EXPORT_DIR / f"{prefix}_{year_suffix}.xlsx"

    logger.info("Exportando %d filas a: %s", df_result.height, export_path)
    df_result.write_excel(export_path)
    logger.info("Exportación completa.")
    return export_path


def _build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos de la CLI `arca-comex-query`.

    Returns:
        Parser de argparse configurado con las opciones de la consulta.
    """
    parser = argparse.ArgumentParser(
        prog="arca-comex-query",
        description=(
            "Consulta declaraciones de importación de ARCA Comex por año, "
            "importador y/o código NCM, y exporta el resultado a un archivo Excel "
            "en outputs/tables/."
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
            "Nombre (o parte del nombre) del importador a buscar. "
            "No distingue mayúsculas/minúsculas."
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
            "(ej. --ncm 73 84.20). Debe indicar --importador y/o --ncm."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Muestra mensajes de registro detallados (nivel DEBUG) en vez de solo INFO.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada de la CLI `arca-comex-query`.

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
    export_query_result(df_result, args.years, args.importador, args.ncm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
