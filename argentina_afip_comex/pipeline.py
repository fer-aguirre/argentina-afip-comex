"""Pipeline mensual de importaciones de ARCA: descarga, conversión, reshape y decodificación.

Cada paso trabaja sobre un único mes, porque el mes (`FECHA_`) identifica por
completo a cada fila: un zip mensual solo contiene filas de ese mes, el reshape
agrupa por una clave que incluye `FECHA_` y la decodificación es fila a fila.
Así, procesar un mes nuevo nunca requiere reprocesar los anteriores.

Lo usan tanto los notebooks `0.0`-`0.4` (para armar el dataset completo en
local) como la CLI `argentina-afip-update` (para agregar solo los meses nuevos
desde GitHub Actions).
"""

import logging
import re
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urljoin

import polars as pl
import polars.selectors as cs
import requests
from bs4 import BeautifulSoup

from argentina_afip_comex.query import DATA_PATH

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
INTERIM_DIR = PROJECT_ROOT / "data" / "interim"
MONTHS_DIR = PROJECT_ROOT / "data" / "processed" / "months"
DOCS_DIR = PROJECT_ROOT / "docs"

ARCA_BASE_URL = "https://www.afip.gob.ar"
ARCA_PAGE_URL = (
    f"{ARCA_BASE_URL}/operadoresComercioExterior/informacionAgregada/"
    "informacion-agregada.asp"
)
# El sitio de ARCA rechaza pedidos sin un User-Agent de navegador.
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# Solo desde 2019 los zips traen el reporte detallado (16 columnas) impo_*.lst;
# los de 2017-2018 usan un formato agregado incompatible.
START_YEAR = 2019

# Matches the month in an ARCA download link, e.g. "...download.aspx?filename=202608.zip".
MONTH_LINK_PATTERN = re.compile(r"filename=(\d{6})\.zip")

# Firma de los archivos zip. ARCA responde 200 con un texto corto (no un zip)
# para los meses que todavía no publicó, así que hay que verificarla.
ZIP_SIGNATURE = b"PK"

# Cada columna cruda salvo COD y MONTO (el par de concepto tributario)
# identifica un ítem de declaración; agrupar por ellas colapsa las filas de
# conceptos tributarios en una sola fila por ítem.
KEY_COLUMNS = [
    "ADU",
    "DESTINACION",
    "NUM_ITEM",
    "FECHA_",
    "NOMBRE_IMPORTADOR",
    "M",
    "UN",
    "CANT_UNIDAD_MEDIDA",
    "FOB_DOLAR",
    "FOB_TOTAL",
    "DIV",
    "PAI",
    "PAI_duplicated_0",
    "POS_NCM",
]

# Catálogos de docs/ usados para decodificar cada columna de código:
# columna cruda -> (archivo, columna con la descripción). UN usa "Descripcion
# Ampliada" porque "Descripcion" es inconsistente/abreviada.
CATALOGS = {
    "ADU": ("ANEXOIV_Aduanas.csv", "Descripcion"),
    "M": ("ANEXOV_Vias_y_Medios_de_Transporte.csv", "Descripcion"),
    "UN": ("ANEXOXV_Unidades_de_medida.csv", "Descripcion Ampliada"),
    "DIV": ("ANEXOXI_Divisas.csv", "Denominacion"),
    "PAI": ("ANEXOVII_Paises.csv", "Denominacion"),
    "PAI_duplicated_0": ("ANEXOVII_Paises.csv", "Denominacion"),
}

# Las dos columnas PAI se renombran antes de decodificar, según el orden de la
# declaración (país de origen antes que país de procedencia).
PAIS_COLUMN_NAMES = {"PAI": "PAIS_ORIGEN", "PAI_duplicated_0": "PAIS_PROCEDENCIA"}

NUMERIC_COLUMNS = ["CANT_UNIDAD_MEDIDA", "FOB_DOLAR", "FOB_TOTAL"]

FINAL_COLUMN_NAMES = {
    "ADU": "ADUANA",
    "FECHA_": "FECHA",
    "NOMBRE_IMPORTADOR": "IMPORTADOR",
    "M": "MEDIO_TRANSPORTE",
    "UN": "UNIDAD_MEDIDA",
    "CANT_UNIDAD_MEDIDA": "CANTIDAD_UNIDAD_MEDIDA",
    # Pese a los nombres de ARCA, los montos están en la moneda de DIV (no
    # siempre dólares). FOB_DOLAR es el valor del ítem (no un precio por
    # unidad) y FOB_TOTAL el total de la declaración, repetido en cada ítem.
    "FOB_DOLAR": "VALOR_FOB_ITEM",
    "FOB_TOTAL": "VALOR_FOB_DECLARACION",
    "DIV": "DIVISA",
    "POS_NCM": "NCM",
}


def list_available_months() -> list[str]:
    """List the months linked from ARCA's aggregated data page.

    The page already has links for the rest of the current year, but inside
    HTML comments until each month is published; comments are ignored here, so
    only published months are listed. `download_month` still checks that the
    file is a zip, in case a link goes live before its file does.

    Returns:
        Sorted YYYYMM strings from START_YEAR onwards.

    Raises:
        requests.HTTPError: If the page can't be fetched.
    """
    response = requests.get(ARCA_PAGE_URL, headers=REQUEST_HEADERS, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    months = {
        match.group(1)
        for link in soup.find_all("a", href=True)
        if (match := MONTH_LINK_PATTERN.search(str(link["href"])))
    }
    return sorted(month for month in months if int(month[:4]) >= START_YEAR)


def download_month(year_month: str) -> Path | None:
    """Download one month's zip from ARCA into data/raw/<year>/<yyyymm>.zip.

    Skips the download if a valid zip is already there. Downloads to a
    temporary file first and renames it into place only once complete, so an
    interrupted download never looks like a valid zip on the next run.

    Args:
        year_month: Month to download, as YYYYMM.

    Returns:
        Path to the zip, or None if ARCA hasn't published that month yet.

    Raises:
        requests.HTTPError: If the download fails.
    """
    zip_path = RAW_DIR / year_month[:4] / f"{year_month}.zip"
    if zip_path.exists() and zipfile.is_zipfile(zip_path):
        logger.debug("%s ya descargado, se omite.", zip_path.name)
        return zip_path

    url = urljoin(
        ARCA_BASE_URL,
        f"/operadoresComercioExterior/informacionAgregada/download.aspx?filename={year_month}.zip",
    )
    with requests.get(
        url, headers=REQUEST_HEADERS, stream=True, timeout=60
    ) as response:
        response.raise_for_status()
        chunks = response.iter_content(chunk_size=1024 * 1024)
        first_chunk = next(chunks, b"")
        if not first_chunk.startswith(ZIP_SIGNATURE):
            logger.info("%s todavía no está publicado en ARCA.", year_month)
            return None

        logger.info("Descargando %s...", zip_path.name)
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = zip_path.with_name(f"{zip_path.name}.tmp")
        with tmp_path.open("wb") as file_:
            file_.write(first_chunk)
            for chunk in chunks:
                file_.write(chunk)

    tmp_path.replace(zip_path)
    return zip_path


def impo_member_crc(zip_path: Path) -> int:
    """Return the CRC-32 of the impo_*.lst report inside a monthly zip.

    ARCA rebuilds the zip on every download, so the zip bytes change even when
    the data doesn't; the inner report's CRC only changes if the data does.

    Args:
        zip_path: Path to a monthly ARCA zip.

    Returns:
        CRC-32 of the impo_*.lst member, as stored in the zip's directory.

    Raises:
        ValueError: If the zip has no impo_*.lst member.
    """
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if Path(info.filename).name.startswith("impo_"):
                return info.CRC
    raise ValueError(f"No impo_*.lst found in {zip_path.name}.")


def convert_month_to_parquet(zip_path: Path) -> Path | None:
    """Convert one month's impo_*.lst report into its own parquet file.

    The report is extracted from its zip into a temporary directory, converted,
    and the temporary directory (and its extracted text) is discarded as soon as
    the parquet has been written, so at most one month's raw text (a few GB)
    ever sits on disk at a time. Skips the conversion if the parquet exists.

    Args:
        zip_path: Path to a monthly ARCA zip archive (e.g. data/raw/2023/202301.zip).

    Returns:
        Path to data/interim/<year>/<yyyymm>/impo_<yyyymm>.parquet, or None if the zip has no impo_*.lst member.
    """
    year_month = zip_path.stem
    month_dir = INTERIM_DIR / year_month[:4] / year_month
    output_path = month_dir / f"impo_{year_month}.parquet"

    if output_path.exists():
        return output_path

    with zipfile.ZipFile(zip_path) as zf:
        impo_members = [
            name for name in zf.namelist() if Path(name).name.startswith("impo_")
        ]
        if not impo_members:
            logger.warning("No impo_*.lst found in %s, skipping.", zip_path.name)
            return None

        month_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp_dir:
            extracted_path = Path(zf.extract(impo_members[0], path=tmp_dir))

            # Eagerly read only the header (takes almost zero memory)
            header_df = pl.read_csv(
                extracted_path, separator="'", quote_char=None, n_rows=0
            )
            clean_columns = [
                col.strip().replace("\x0c", "") for col in header_df.columns
            ]

            # LAZY read: scan_csv doesn't load data into memory yet.
            lazy_df = pl.scan_csv(
                extracted_path,
                separator="'",
                quote_char=None,
                skip_rows=2,
                has_header=False,
                new_columns=clean_columns,
                infer_schema_length=0,
            )
            lazy_df = lazy_df.with_columns(cs.string().str.strip_chars())

            # The source .lst files are paginated reports: every form-feed page break
            # repeats the header row and a '---------' separator row, which otherwise
            # leak into the data as garbage rows. FECHA_ is always a 6-digit YYYYMM
            # value in real rows, so use it to drop those repeated header/separator rows.
            lazy_df = lazy_df.filter(pl.col("FECHA_").str.contains(r"^\d{6}$"))

            # Streams the month into parquet before the temporary directory
            # (and the extracted text) is cleaned up.
            lazy_df.sink_parquet(output_path)

    return output_path


def reshape_month(interim_path: Path) -> Path:
    """Collapse one month's tax-concept rows into one row per declaration item.

    The raw report has one row per (declaration item, tax concept) pair, with
    every shipment-level field repeated and only MONTO varying. MONTO is summed
    into MONTO_TRIBUTADO_TOTAL and COD is dropped. Skips the reshape if the
    output exists.

    Args:
        interim_path: Month parquet written by `convert_month_to_parquet`.

    Returns:
        Path to the reshaped month parquet, next to interim_path.
    """
    year_month = interim_path.parent.name
    output_path = interim_path.with_name(f"impo_{year_month}_reshaped.parquet")
    if output_path.exists():
        return output_path

    lf = pl.scan_parquet(interim_path)
    # MONTO is a padded string in the raw data; empty strings (no tax charged)
    # become null before casting so they don't fail the cast.
    lf = lf.with_columns(pl.col("MONTO").replace("", None).cast(pl.Float64))
    lf = lf.group_by(KEY_COLUMNS).agg(
        pl.col("MONTO").sum().alias("MONTO_TRIBUTADO_TOTAL")
    )
    lf.sink_parquet(output_path)
    return output_path


def _load_catalog(column: str) -> pl.DataFrame:
    """Load the docs/ catalog (ANEXO) for a raw code column.

    Args:
        column: Raw code column, one of CATALOGS' keys.

    Returns:
        DataFrame with the `Codigo` column and the catalog's description column.
    """
    filename, desc_col = CATALOGS[column]
    # `Codigo` must be forced to Utf8 -- otherwise polars infers it as an integer and
    # strips the leading zeros that the raw codes rely on (e.g. "001" -> 1).
    return pl.read_csv(
        DOCS_DIR / filename,
        separator="|",
        quote_char='"',
        schema_overrides={"Codigo": pl.Utf8},
    ).select("Codigo", desc_col)


def decode_month(reshaped_path: Path) -> Path:
    """Decode one reshaped month's ARCA codes and give columns their final names.

    Each code column in CATALOGS is replaced in place with its description;
    codes with no catalog match (e.g. blank M when no transport medium was
    recorded) become null rather than failing the join. Numeric columns are
    cast to Float64 (empty strings become null). Skips the decode if the
    output exists.

    Args:
        reshaped_path: Month parquet written by `reshape_month`.

    Returns:
        Path to data/processed/months/importaciones_<yyyymm>_decoded.parquet.
    """
    year_month = reshaped_path.parent.name
    output_path = MONTHS_DIR / f"importaciones_{year_month}_decoded.parquet"
    if output_path.exists():
        return output_path

    lf = pl.scan_parquet(reshaped_path)
    for column in CATALOGS:
        lookup = _load_catalog(column)
        decoded_column = f"__{column}_decoded"
        lookup.columns = [column, decoded_column]
        lf = lf.join(lookup.lazy(), on=column, how="left")
        lf = lf.with_columns(pl.col(decoded_column).alias(column)).drop(decoded_column)

    lf = lf.with_columns(
        [pl.col(col).replace("", None).cast(pl.Float64) for col in NUMERIC_COLUMNS]
    )
    lf = lf.rename(PAIS_COLUMN_NAMES | FINAL_COLUMN_NAMES)

    MONTHS_DIR.mkdir(parents=True, exist_ok=True)
    lf.sink_parquet(output_path)
    return output_path


def unknown_codes(reshaped_path: Path) -> dict[str, dict[str, int]]:
    """Find non-blank codes missing from the docs/ catalogs in a reshaped month.

    Those codes become null after decoding, so they flag catalog entries that
    ARCA added after the catalogs in docs/ were saved. Blank codes (e.g. M
    when no transport medium was recorded) are expected and not reported.

    Args:
        reshaped_path: Month parquet written by `reshape_month`.

    Returns:
        Mapping of raw column -> {unknown code: number of rows}, only for
        columns that have unknown codes.
    """
    lf = pl.scan_parquet(reshaped_path)
    result = {}
    for column in CATALOGS:
        known_codes = _load_catalog(column)["Codigo"]
        df_unknown = (
            lf.filter((pl.col(column) != "") & ~pl.col(column).is_in(known_codes))
            .group_by(column)
            .len()
            .collect()
        )
        if df_unknown.height:
            result[column] = dict(df_unknown.iter_rows())
    return result


def combine_months(month_paths: list[Path], extend_existing: bool) -> None:
    """Combine decoded month files into the final dataset at DATA_PATH.

    Writes to a temporary file and renames it into place, so a failure never
    leaves a half-written dataset behind.

    Args:
        month_paths: Decoded month parquets from `decode_month`.
        extend_existing: If True, add the months to the existing dataset at
            DATA_PATH, dropping its rows for those months first so re-adding a
            month replaces it instead of duplicating it. If False, build the
            dataset from `month_paths` only.
    """
    frames = [pl.scan_parquet(month_paths)]
    if extend_existing:
        new_months = [path.stem.split("_")[1] for path in month_paths]
        frames.insert(
            0, pl.scan_parquet(DATA_PATH).filter(~pl.col("FECHA").is_in(new_months))
        )

    tmp_path = DATA_PATH.with_name(f"{DATA_PATH.name}.tmp")
    pl.concat(frames).sink_parquet(tmp_path)
    tmp_path.replace(DATA_PATH)
