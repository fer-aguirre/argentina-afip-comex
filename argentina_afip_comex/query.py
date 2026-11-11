"""Consulta y exportación de declaraciones de importación de ARCA Comex.

Funciona tanto como librería como CLI (`argentina-afip-query`):

    from argentina_afip_comex import Consulta, export_query_result, query_data

    consulta = Consulta(years=[2024, 2025], codigo="2701")
    df_result = query_data(consulta)
    export_query_result(df_result, consulta)

El archivo exportado es CSV por defecto (`formato`/--formato/-f también acepta
"xlsx" y "parquet") y va por defecto al directorio actual; usar
`output_dir`/--output/-o para exportarlo a otra carpeta (que se crea si no
existe). Los notebooks pasan `output_dir=utils.outputs_tables_dir()`. El
nombre del archivo lo arma `Consulta.export_filename` (ver `consulta.py`).

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

from argentina_afip_comex import utils
from argentina_afip_comex.consulta import NCM_NON_DIGIT_PATTERN, Consulta

logger = logging.getLogger(__name__)

# Nombre fijo del archivo tal como se sube a cada GitHub release: la URL de
# "latest" necesita un nombre de archivo conocido de antemano, así que no
# incluye el rango de fechas, que crece con cada actualización.
DECODED_FILENAME = "importaciones_decoded.parquet"
RELEASE_DOWNLOAD_URL = (
    "https://github.com/fer-aguirre/argentina-afip-comex/releases/latest/download/"
    + DECODED_FILENAME
)

# Formatos de archivo aceptados para exportar el resultado de una consulta.
EXPORT_FORMATS = ("csv", "xlsx", "parquet")


def download_decoded_data() -> None:
    """Download the pre-built decoded dataset from the latest GitHub release.

    Downloads to a temporary file first and renames it into place only once
    complete, so an interrupted download never leaves a truncated file that
    looks like a valid cached dataset on the next run.
    """
    destination = utils.data_processed_dir(DECODED_FILENAME)
    logger.info(
        "Dataset no encontrado localmente. Descargando desde %s...",
        RELEASE_DOWNLOAD_URL,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_name(f"{destination.name}.tmp")

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

    tmp_path.replace(destination)
    logger.info("Descarga completa: %s", destination)


def query_data(consulta: Consulta) -> pl.DataFrame:
    """Consulta el dataset de importaciones decodificado.

    Agrega dos columnas derivadas de FECHA (una cadena YYYYMM): AÑO y MES.
    Si el dataset no existe localmente, se descarga primero desde el release
    más reciente en GitHub (ver RELEASE_DOWNLOAD_URL).

    Args:
        consulta: Parámetros de la búsqueda (años, nombre y/o código NCM).

    Returns:
        DataFrame de polars con las filas que cumplen los filtros.
    """
    year_strs = [str(year) for year in consulta.year_values]
    filters = [pl.col("FECHA").str.slice(0, 4).is_in(year_strs)]

    if consulta.nombre_value is not None:
        # Escapado para que caracteres como "." o "(" se busquen literalmente.
        filters.append(
            pl.col("IMPORTADOR").str.contains(f"(?i){re.escape(consulta.nombre_value)}")
        )

    if consulta.codigo_values:
        # La columna NCM tiene puntos ("8420.10.00"): se comparan solo los dígitos.
        ncm_digits = pl.col("NCM").str.replace_all(NCM_NON_DIGIT_PATTERN.pattern, "")
        codes = consulta.codigo_values
        ncm_filter = ncm_digits.str.starts_with(codes[0])
        for code in codes[1:]:
            ncm_filter = ncm_filter | ncm_digits.str.starts_with(code)
        filters.append(ncm_filter)

    combined_filter = filters[0]
    for extra_filter in filters[1:]:
        combined_filter = combined_filter & extra_filter

    data_path = utils.data_processed_dir(DECODED_FILENAME)
    if not data_path.exists():
        download_decoded_data()

    return (
        pl.scan_parquet(data_path)
        .filter(combined_filter)
        .with_columns(
            pl.col("FECHA").str.slice(0, 4).cast(pl.Int64).alias("AÑO"),
            pl.col("FECHA").str.slice(4, 2).cast(pl.Int64).alias("MES"),
        )
        .collect()
    )


def export_query_result(
    df_result: pl.DataFrame,
    consulta: Consulta,
    output_dir: Path | None = None,
    formato: str = "csv",
) -> Path | None:
    """Exporta el resultado de una consulta a un archivo.

    El nombre del archivo se arma a partir de la consulta, con la fecha y
    hora de exportación, hasta segundos (ver `Consulta.export_filename`).

    Args:
        df_result: DataFrame a exportar, resultado de `query_data(consulta)`.
        consulta: La misma consulta usada para obtener `df_result`.
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

    export_dir = output_dir if output_dir is not None else Path.cwd()
    if not export_dir.exists():
        logger.info("El directorio de salida no existe, se crea: %s", export_dir)
        export_dir.mkdir(parents=True)
    export_path = export_dir / consulta.export_filename(formato)

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
            "--nombre y/o --codigo."
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
        "-n",
        "--nombre",
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
        "-c",
        "--codigo",
        type=str,
        nargs="+",
        default=None,
        metavar="NCM",
        help=(
            "Uno o más códigos NCM (o prefijos) a buscar, separados por espacios "
            "(ej. --codigo 73 84.20). Los puntos son opcionales (84.20 y 8420 son "
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
        correctamente. Si los argumentos son inválidos, argparse termina el
        proceso con código 2.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    try:
        consulta = Consulta(years=args.years, nombre=args.nombre, codigo=args.codigo)
    except ValueError as error:
        parser.error(str(error))

    df_result = query_data(consulta)
    export_query_result(
        df_result, consulta, output_dir=args.output, formato=args.formato
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
