# AFIP Comercio Exterior

Análisis de datos de ARCA (AFIP) para comercio exterior en Argentina.

Created by: Fernanda Aguirre Ruiz

---

## Instalación

Este proyecto usa [uv](https://docs.astral.sh/uv/) para gestionar dependencias y el entorno virtual.

```bash
uv sync
```

Esto instala las dependencias y el paquete `arca_comex` en modo editable, lo que habilita tanto el import (`from arca_comex.query import query_importaciones`) en notebooks/scripts como el comando de consola `arca-comex-query`.

## Uso de la CLI

`arca-comex-query` consulta el dataset de importaciones ya procesado (`data/processed/importaciones_2019-2026_decoded.parquet`) por año, importador y/o código NCM, y exporta el resultado a un archivo Excel en `outputs/tables/`.

```bash
uv run arca-comex-query --years 2023 2024 --importador "acme"
uv run arca-comex-query --years 2024 --ncm 73 84.20
uv run arca-comex-query --help
```

También puede usarse como librería, por ejemplo desde un notebook:

```python
from arca_comex.query import export_query_result, query_importaciones

df = query_importaciones(years=[2023, 2024], ncm="2701")
export_query_result(df, query_years=[2023, 2024], query_importador=None, query_ncm="2701")
```

---
## Estructura de directorios
```
┬
├─ .gitignore                     # Configuración de Git para ignorar archivos
├─ LICENSE                        # Licencia del proyecto
├─ pyproject.toml                 # Dependencias y configuración del paquete
├─ README.md                      # Este archivo
|
├─ arca_comex                     # Paquete Python: librería + CLI de consulta
|  ├─ __init__.py
|  └─ query.py                    # query_importaciones / export_query_result / CLI arca-comex-query
|
├─ assets                         # Recursos del proyecto
|
├─ data                           # Datos categorizados
|  ├─ raw                         # Zips mensuales originales descargados de AFIP, por año
|  ├─ interim                     # Parquets mensuales intermedios, por año/mes
|  ├─ processed                   # Parquets combinados, reformados y decodificados
|  └─ review                      # Archivos de revisión manual de consultas puntuales
|
├─ docs                           # Catálogos de referencia de AFIP (ANEXOs) usados para decodificar códigos
|
├─ notebooks                      # Notebooks del pipeline de datos
|  ├─ 0.0-collect-data.ipynb      # Descarga los zips mensuales desde AFIP
|  ├─ 0.2-convert-parquet.ipynb   # Convierte los reportes .lst a parquet y los combina en un único archivo
|  ├─ 0.3-reshape-data.ipynb      # Colapsa las filas por concepto tributario en una fila por ítem de declaración
|  ├─ 0.4-decode-data.ipynb       # Decodifica los códigos AFIP usando los catálogos de docs/
|  └─ 0.5-query-data.ipynb        # Ejemplos de uso de arca_comex.query
|
├─ outputs                        # Exports generados por los notebooks y por la CLI
|  ├─ figures                     # Gráficos, mapas, etc. para reportes
|  └─ tables                      # Resultados de consultas exportados a Excel
|
┴

```

---

### Diccionario de datos para `importaciones_2019-2026_decoded.parquet`

| Column | Type | Source | Description |
|--------|------|--------|-------------|
| ADUANA | string | ANEXOIV | Aduana donde se registró la importación |
| DESTINACION | string | — | Número de registro de la declaración de importación |
| NUM_ITEM | string | — | Número de ítem dentro de la declaración |
| FECHA | string | — | Fecha de oficialización (formato YYYYMM) |
| IMPORTADOR | string | — | Nombre completo del importador |
| MEDIO_TRANSPORTE | string | ANEXOV | Medio de transporte (ej. CAMION, AVION, ACUATICO) |
| UNIDAD_MEDIDA | string | ANEXOXV | Unidad de medida (ej. TONELADA, UNIDAD, KILOGRAMO) |
| CANTIDAD_UNIDAD_MEDIDA | float64 | — | Cantidad en la unidad de medida especificada |
| FOB_UNITARIO_USD | float64 | — | Valor FOB/CIF unitario en USD |
| FOB_TOTAL_USD | float64 | — | Valor FOB/CIF total en USD |
| DIVISA | string | ANEXOXI | Divisa (ej. DOLAR, EURO, GUARANI) |
| PAIS_ORIGEN | string | ANEXOVII | País de origen |
| PAIS_PROCEDENCIA | string | ANEXOVII | País de procedencia |
| NCM | string | — | Posición arancelaria del Mercosur (no decodificada — catálogo externo) |
| MONTO_TRIBUTADO_TOTAL | float64 | — | Suma de todos los montos tributados de la declaración (ver `0.3-reshape-data.ipynb`) |

---

## License

This project is released under [MIT License](/LICENSE).

---

This repository was generated with [cookiecutter](https://github.com/fer-aguirre/cookiecutter-data-analysis-lite).
