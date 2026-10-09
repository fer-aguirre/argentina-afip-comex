"""Actualización incremental del dataset con los meses nuevos que publique ARCA.

CLI `argentina-afip-update`, pensada para correr periódicamente en GitHub
Actions (ver `.github/workflows/update-data.yml`), aunque también funciona en
local. Compara los meses que lista ARCA con los ya procesados en
`data/manifest.json`, procesa solo los nuevos (ver `pipeline`) y los agrega al
dataset final. Los meses ya procesados nunca se vuelven a descargar.

Publicar el release y commitear el manifest quedan a cargo del workflow; esta
CLI le informa qué cambió a través de `GITHUB_OUTPUT` cuando corre en Actions.
"""

import argparse
import json
import logging
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from argentina_afip_comex.pipeline import (
    PROJECT_ROOT,
    combine_months,
    convert_month_to_parquet,
    decode_month,
    download_month,
    impo_member_crc,
    list_available_months,
    reshape_month,
    unknown_codes,
)
from argentina_afip_comex.query import DATA_PATH, download_decoded_data

logger = logging.getLogger(__name__)

MANIFEST_PATH = PROJECT_ROOT / "data" / "manifest.json"

# Proporción máxima de filas de un mes con códigos que no están en los
# catálogos de docs/ (y que por lo tanto quedan vacíos al decodificar). En los
# datos 2019-2026 son 8 filas de ~43 millones, así que superar este umbral
# indica que ARCA agregó códigos nuevos y hay que actualizar los catálogos.
MAX_UNKNOWN_CODE_SHARE = 0.001

# Hora de Argentina (UTC-3, sin horario de verano), para fechar el procesamiento.
ARGENTINA_TZ = timezone(timedelta(hours=-3))


@dataclass
class MonthRecord:
    """Registro de un mes ya procesado, tal como se guarda en el manifest.

    Attributes:
        impo_crc32: CRC-32 del reporte impo_*.lst dentro del zip de ARCA, para
            poder detectar si ARCA lo corrige más adelante.
        rows: Filas del mes en el dataset decodificado.
        processed_at: Fecha de procesamiento, en formato ISO (AAAA-MM-DD).
    """

    impo_crc32: int
    rows: int
    processed_at: str


def load_manifest() -> dict[str, MonthRecord]:
    """Read the processed months from data/manifest.json.

    Returns:
        Mapping of YYYYMM -> MonthRecord, empty if the manifest doesn't exist.
    """
    if not MANIFEST_PATH.exists():
        return {}
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {month: MonthRecord(**record) for month, record in raw.items()}


def save_manifest(manifest: dict[str, MonthRecord]) -> None:
    """Write the processed months to data/manifest.json, sorted by month.

    Args:
        manifest: Mapping of YYYYMM -> MonthRecord.
    """
    raw = {month: asdict(manifest[month]) for month in sorted(manifest)}
    MANIFEST_PATH.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")


def _format_month(year_month: str) -> str:
    """Format YYYYMM as YYYY-MM for logs and release notes.

    Args:
        year_month: Month as YYYYMM.

    Returns:
        Month as YYYY-MM.
    """
    return f"{year_month[:4]}-{year_month[4:]}"


def _check_unknown_codes(reshaped_path: Path, rows: int) -> None:
    """Fail if too many of a month's rows have codes missing from the catalogs.

    Args:
        reshaped_path: Month parquet written by `reshape_month`.
        rows: Number of rows in that month.

    Raises:
        ValueError: If any column's unknown codes exceed MAX_UNKNOWN_CODE_SHARE
            of the month's rows.
    """
    for column, codes in unknown_codes(reshaped_path).items():
        share = sum(codes.values()) / rows
        if share > MAX_UNKNOWN_CODE_SHARE:
            raise ValueError(
                f"{column}: {share:.2%} de las filas de {reshaped_path.name} tienen "
                f"códigos que no están en los catálogos de docs/: {codes}. "
                "Actualizar el catálogo correspondiente y volver a correr."
            )
        logger.warning("%s: códigos sin catálogo (se dejan vacíos): %s", column, codes)


def _write_github_outputs(outputs: dict[str, str]) -> None:
    """Pass values to later workflow steps when running in GitHub Actions.

    Args:
        outputs: Output name -> value. Ignored outside GitHub Actions.
    """
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file is None:
        return
    with Path(output_file).open("a", encoding="utf-8") as file_:
        file_.writelines(f"{name}={value}\n" for name, value in outputs.items())


def update() -> list[str]:
    """Process every month ARCA has published that isn't in the manifest yet.

    New months are downloaded, converted, reshaped and decoded one at a time,
    then added to the dataset at DATA_PATH (downloaded first from the latest
    release if it isn't there). The manifest is saved only after the dataset
    is written.

    Returns:
        The YYYYMM months added, sorted; empty if there was nothing new.
    """
    manifest = load_manifest()
    pending = [m for m in list_available_months() if m not in manifest]
    logger.info("Meses en ARCA sin procesar: %s", pending or "ninguno")

    new_records: dict[str, MonthRecord] = {}
    decoded_paths = []
    for year_month in pending:
        zip_path = download_month(year_month)
        if zip_path is None:
            # Link live but file not published yet; later months won't be either.
            break

        logger.info("Procesando %s...", _format_month(year_month))
        crc = impo_member_crc(zip_path)
        interim_path = convert_month_to_parquet(zip_path)
        if interim_path is None:
            raise ValueError(f"{zip_path.name} no contiene un reporte impo_*.lst.")
        reshaped_path = reshape_month(interim_path)
        decoded_path = decode_month(reshaped_path)

        rows = pl.scan_parquet(decoded_path).select(pl.len()).collect().item()
        _check_unknown_codes(reshaped_path, rows)

        decoded_paths.append(decoded_path)
        new_records[year_month] = MonthRecord(
            impo_crc32=crc,
            rows=rows,
            processed_at=datetime.now(ARGENTINA_TZ).date().isoformat(),
        )

    if not decoded_paths:
        return []

    if not DATA_PATH.exists():
        download_decoded_data()
    logger.info("Agregando %d mes(es) a %s...", len(decoded_paths), DATA_PATH)
    combine_months(decoded_paths, extend_existing=True)

    manifest.update(new_records)
    save_manifest(manifest)
    return sorted(new_records)


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada de la CLI `argentina-afip-update`.

    Args:
        argv: Argumentos de línea de comandos a parsear. Si es `None`, se
            usan los de `sys.argv`.

    Returns:
        Código de salida del proceso: 0 si la actualización terminó bien.
    """
    parser = argparse.ArgumentParser(
        prog="argentina-afip-update",
        description=(
            "Descarga y procesa los meses que ARCA publicó desde la última "
            "actualización, y los agrega a data/processed/"
            f"{DATA_PATH.name}. Los meses ya procesados se leen de "
            "data/manifest.json."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Muestra mensajes de registro detallados (nivel DEBUG) en vez de solo INFO.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    added = update()
    if not added:
        logger.info("No hay meses nuevos. El dataset ya está al día.")
        _write_github_outputs({"updated": "false"})
        return 0

    last_month = max(load_manifest())
    logger.info(
        "Dataset actualizado hasta %s. Meses agregados: %s.",
        _format_month(last_month),
        ", ".join(_format_month(m) for m in added),
    )
    _write_github_outputs(
        {
            "updated": "true",
            "added_months": ", ".join(_format_month(m) for m in added),
            "last_month": _format_month(last_month),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
