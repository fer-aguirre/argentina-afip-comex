# Argentina AFIP Comercio Exterior

Importaciones de Argentina, a partir de la información agregada que publica ARCA (ex AFIP), en una sola tabla limpia y fácil de consultar.

Creado por: Fernanda Aguirre Ruiz

---

## ¿Qué es esto?

ARCA publica cada mes información de las declaraciones de importación de Argentina: quién importó qué producto, por qué monto, desde qué país, por qué aduana, etc. Esos archivos son difíciles de usar tal como vienen:

- Se publican en zips mensuales, con reportes de texto de ancho fijo.
- Usan códigos internos en vez de nombres (por ejemplo, un número en lugar del nombre del país).
- Repiten cada ítem de una declaración una vez por cada impuesto que pagó, así que contar filas o sumar montos directamente da resultados inflados.

Este proyecto toma esos archivos y arma **una sola tabla limpia**:

- **Desde enero de 2019**, con más de 43 millones de filas.
- **Una fila por ítem de declaración** (un producto dentro de una declaración de importación).
- Con aduanas, países, monedas, unidades y medios de transporte **traducidos a su nombre**.
- **Actualizada todos los meses** de forma automática (ver [Actualización automática](#actualización-automática)).

> Por ahora solo incluye **importaciones**. Los años 2017 y 2018 quedan afuera porque ARCA los publica en un formato distinto, incompatible con el resto.

---

## Por dónde empezar

**Si querés buscar datos sin escribir código:**
Abrí [`notebooks/0.5-query-data.ipynb`](notebooks/0.5-query-data.ipynb) en Jupyter o VS Code, cambiá los valores de la celda de configuración (años, importador, código NCM, formato) y ejecutá todas las celdas. El resultado se muestra en el notebook y se guarda en `outputs/tables/`.

**Si preferís la terminal:**
```bash
uv run argentina-afip-query --years 2024 --ncm 2701 --importador "acme"
```
Más ejemplos en [Consultar los datos](#consultar-los-datos).

**Si vas a analizar los datos:**
Leé primero [Qué tener en cuenta al analizar](#qué-tener-en-cuenta-al-analizar) y el [diccionario de datos](#diccionario-de-datos).

**Si querés entender o modificar cómo se arma la tabla:**
Mirá [Cómo se arma la tabla](#cómo-se-arma-la-tabla) y [Actualización automática](#actualización-automática).

---

## Instalación

El proyecto usa [`uv`](https://docs.astral.sh/uv/), una herramienta que instala Python y todas las librerías necesarias en las versiones exactas del proyecto (definidas en `pyproject.toml` y `uv.lock`). Si todavía no la tenés, seguí su [guía de instalación](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/fer-aguirre/argentina-afip-comex.git
cd argentina-afip-comex
uv sync
```

`uv sync` crea una carpeta `.venv` con todo lo necesario, incluido el comando `argentina-afip-query`. Todos los comandos de este README se corren desde la carpeta del proyecto.

---

## Conseguir los datos

La tabla final es un único archivo, `importaciones_decoded.parquet` (~900 MB). Parquet es un formato de tabla comprimido, mucho más liviano y rápido que un CSV; se abre con Python (polars, pandas), R o DuckDB.

**No hace falta descargarla a mano.** La primera vez que corrés una consulta (con el notebook `0.5` o desde la terminal), si el archivo no está en `data/processed/`, se descarga solo desde el [release más reciente](https://github.com/fer-aguirre/argentina-afip-comex/releases/latest) del repositorio. Un *release* es una versión publicada del dataset en GitHub; también podés bajar el archivo desde esa página.

> **Para tener los meses más recientes:** tu copia local no se actualiza sola. Borrá `data/processed/importaciones_decoded.parquet` y volvé a correr una consulta: se descarga la versión más nueva. Hasta qué mes llega cada versión figura en las notas del [release más reciente](https://github.com/fer-aguirre/argentina-afip-comex/releases/latest) y en [`data/manifest.json`](data/manifest.json).

Si preferís armar la tabla desde cero, con los archivos originales de ARCA, seguí los pasos de [Cómo se arma la tabla](#cómo-se-arma-la-tabla). El proceso completo necesita unos 30 GB libres en disco.

---

## Consultar los datos

Las consultas funcionan igual desde un notebook o desde la terminal. Hay que indicar al menos un **importador** o un **código NCM**, para no recorrer las 43 millones de filas sin acotar.

| Filtro | Qué es | Ejemplo |
|---|---|---|
| `years` | Año o lista de años | `2024` / `[2023, 2024, 2025]` |
| `importador` *(opcional)* | Nombre del importador. Busca coincidencias parciales, sin distinguir mayúsculas de minúsculas; podés escribir puntos o paréntesis tal cual (ej. `"s.a."`). Cuanto más específico, mejor: un término corto como `"sa"` puede devolver miles de resultados. | `"acme"` |
| `ncm` *(opcional)* | Código NCM (el código del producto en el Mercosur), completo o solo el comienzo. Los puntos son opcionales: `84.20` = `8420`. | `"2701"` |

**Desde un notebook:**
```python
from argentina_afip_comex.query import (
    OUTPUTS_TABLES_DIR,
    export_query_result,
    query_importaciones,
)

resultado = query_importaciones(years=[2024, 2025], ncm="2701")
export_query_result(
    resultado, [2024, 2025], None, "2701", output_dir=OUTPUTS_TABLES_DIR, formato="xlsx"
)
```

**Desde la terminal:**
```bash
uv run argentina-afip-query --years 2024 2025 -n 2701 -f xlsx
uv run argentina-afip-query --years 2023 2024 -i "acme" -o outputs/tables
```
Por defecto guarda un CSV en la carpeta donde estás parado/a. Con `-o` elegís otra carpeta (se crea si no existe) y con `-f` el formato: `csv`, `xlsx` o `parquet`. Todas las opciones aparecen con `--help`.

El resultado trae las columnas del [diccionario de datos](#diccionario-de-datos), más `AÑO` y `MES` (calculadas a partir de `FECHA`) para filtrar o agrupar más fácil.

> **¿CSV o Excel?** El CSV es el formato por defecto porque no tiene límite de filas. Excel admite como máximo 1.048.576 filas por hoja, así que una búsqueda amplia (por ejemplo, un capítulo NCM entero en varios años) puede no entrar en un `.xlsx`.

> **En Windows**, si `uv run argentina-afip-query` falla con un error de que una directiva bloqueó el archivo, usá: `uv run python -m argentina_afip_comex --years 2024 --ncm 2701`.

### Analizar la tabla completa

Para análisis que van más allá de un filtro (agregados por país, series de tiempo, etc.), podés leer la tabla directamente en tu propio notebook. Con [polars](https://docs.pola.rs/) y `scan_parquet`, la consulta solo lee las columnas y filas que necesita:

```python
import polars as pl

from argentina_afip_comex.query import DATA_PATH

# Valor FOB/CIF importado en 2024 por país de origen, solo ítems declarados en dólares.
# Se suma VALOR_FOB_ITEM, no VALOR_FOB_DECLARACION (que se repite en cada ítem):
# ver "Qué tener en cuenta al analizar".
df_por_pais = (
    pl.scan_parquet(DATA_PATH)
    .filter(
        pl.col("FECHA").str.starts_with("2024"),
        pl.col("DIVISA") == "DOLAR ESTADOUNIDENSE",
    )
    .group_by("PAIS_ORIGEN")
    .agg(pl.col("VALOR_FOB_ITEM").sum().alias("FOB_USD"))
    .sort("FOB_USD", descending=True)
    .collect()
)
```

---

## Qué tener en cuenta al analizar

- **Una fila es un ítem, no una declaración.** Una declaración que importa cinco productos distintos aparece en cinco filas. Para contar declaraciones, contá valores únicos de `DESTINACION`.
- **Los montos FOB/CIF no siempre están en dólares.** Están en la moneda de la columna `DIVISA`: en 2024, el 85% de los ítems está en dólares, el 9% en euros, el 3% en pesos y el resto en otras monedas. La especificación de ARCA no indica moneda para estos campos (aunque el reporte original llama `FOB_DOLAR` a uno de ellos). Antes de sumar, filtrá por `DIVISA` o convertí cada moneda.
- **`VALOR_FOB_DECLARACION` es el total de la declaración, repetido en cada ítem.** No hay que sumarlo fila por fila: el resultado queda multiplicado por la cantidad de ítems. Para sumar montos usá `VALOR_FOB_ITEM`. En el 82% de las declaraciones, la suma de sus ítems coincide exactamente con `VALOR_FOB_DECLARACION`; en el resto hay diferencias que todavía no están explicadas.
- **Las fechas son mensuales.** `FECHA` es el mes de oficialización de la declaración (`AAAAMM`), sin día.
- **Los impuestos están sumados.** `MONTO_TRIBUTADO_TOTAL` es la suma de todos los conceptos tributarios del ítem; el detalle por impuesto no se conserva.
- **Los códigos sin catálogo quedan vacíos.** Si un mes trae una aduana, país, moneda, unidad o medio de transporte que no figura en los catálogos de ARCA (`docs/`), ese campo queda vacío. La actualización se frena si eso pasa en más del 0,1% de las filas de un mes (ver [Actualización automática](#actualización-automática)).
- **El NCM no se traduce.** Queda como código (ej. `8420.10.90`); para saber qué producto es hay que consultar el nomenclador del Mercosur.
- **Las correcciones de ARCA no se detectan.** Cada mes se procesa una sola vez. Si ARCA corrige después un mes ya publicado, la tabla mantiene la versión original.

---

## Diccionario de datos

Columnas de `importaciones_decoded.parquet`. La columna "Catálogo" indica qué anexo de ARCA (en [`docs/`](docs/)) se usó para traducir el código a su nombre.

| Columna | Tipo | Catálogo | Descripción |
|---|---|---|---|
| ADUANA | texto | ANEXOIV | Aduana donde se registró la importación |
| DESTINACION | texto | — | Número de registro de la declaración de importación |
| NUM_ITEM | texto | — | Número de ítem dentro de la declaración |
| FECHA | texto | — | Mes de oficialización (formato AAAAMM, ej. `202401`) |
| IMPORTADOR | texto | — | Nombre completo del importador |
| MEDIO_TRANSPORTE | texto | ANEXOV | Medio de transporte (ej. CAMION, AVION, ACUATICO) |
| UNIDAD_MEDIDA | texto | ANEXOXV | Unidad de medida (ej. TONELADA, UNIDAD, KILOGRAMO) |
| CANTIDAD_UNIDAD_MEDIDA | número | — | Cantidad en la unidad de medida indicada |
| VALOR_FOB_ITEM | número | — | Valor FOB/CIF del ítem, en la moneda de `DIVISA` (ARCA lo llama "valor unitario", pero no es un precio por unidad) |
| VALOR_FOB_DECLARACION | número | — | Valor FOB/CIF total de la declaración, en la moneda de `DIVISA`, repetido en cada ítem |
| DIVISA | texto | ANEXOXI | Divisa (ej. DOLAR, EURO, GUARANI) |
| PAIS_ORIGEN | texto | ANEXOVII | País de origen |
| PAIS_PROCEDENCIA | texto | ANEXOVII | País de procedencia |
| NCM | texto | — | Posición arancelaria del Mercosur, con puntos (ej. `8420.10.90`) |
| MONTO_TRIBUTADO_TOTAL | número | — | Suma de todos los montos tributados del ítem |

La especificación oficial de ARCA para estos archivos está en [`docs/Procedimiento-descarga-y-lectura-archivos-de-ComExAFIP-2018.pdf`](docs/Procedimiento-descarga-y-lectura-archivos-de-ComExAFIP-2018.pdf).

---

## Cómo se arma la tabla

El proceso está dividido en notebooks numerados que se corren en orden: cada uno usa los archivos que deja el anterior. Todos trabajan **mes por mes** y saltean los meses que ya procesaron, así que volver a correrlos solo procesa lo que falta. Cada notebook explica en su primera celda qué hace y por qué.

| Notebook | Qué hace | Entrada | Salida |
|---|---|---|---|
| [`0.0-collect-data.ipynb`](notebooks/0.0-collect-data.ipynb) | Descarga los zips mensuales desde el sitio de ARCA (desde 2019). | Sitio de ARCA | `data/raw/<año>/<aaaamm>.zip` |
| [`0.2-convert-parquet.ipynb`](notebooks/0.2-convert-parquet.ipynb) | Convierte el reporte de texto de cada mes a parquet. | `data/raw/<año>/<aaaamm>.zip` | `data/interim/<año>/<aaaamm>/impo_<aaaamm>.parquet` |
| [`0.3-reshape-data.ipynb`](notebooks/0.3-reshape-data.ipynb) | Junta las filas repetidas por impuesto en una sola fila por ítem de declaración, sumando los montos tributados. | `impo_<aaaamm>.parquet` | `impo_<aaaamm>_reshaped.parquet` (misma carpeta) |
| [`0.4-decode-data.ipynb`](notebooks/0.4-decode-data.ipynb) | Traduce los códigos de ARCA (aduana, país, moneda, unidad, transporte) a su nombre con los catálogos de `docs/` y une todos los meses en la tabla final. | `impo_<aaaamm>_reshaped.parquet` | `data/processed/importaciones_decoded.parquet` |
| [`0.5-query-data.ipynb`](notebooks/0.5-query-data.ipynb) | Consulta la tabla final y exporta el resultado. | `importaciones_decoded.parquet` | CSV, Excel o parquet en `outputs/tables/` |

El código de cada paso está en [`argentina_afip_comex/pipeline.py`](argentina_afip_comex/pipeline.py), el mismo que usa la actualización automática.

---

## Actualización automática

ARCA publica cada mes nuevo el día 1 del mes siguiente. Un proceso automático en GitHub (un *workflow* de GitHub Actions, definido en [`.github/workflows/update-data.yml`](.github/workflows/update-data.yml)) revisa **del 1 al 7 de cada mes, a las 09:14 (hora de Argentina)**, si hay meses nuevos. Si los hay:

1. Descarga y procesa **solo esos meses**.
2. Los agrega a la tabla final y publica un [release](https://github.com/fer-aguirre/argentina-afip-comex/releases/latest) nuevo, con la fecha de la actualización como nombre (ej. `v2026.10.09`). Solo se conserva el release más reciente.
3. Anota los meses agregados en [`data/manifest.json`](data/manifest.json), el registro de meses procesados: para cada mes guarda cuántas filas tiene y cuándo se procesó.

Si no hay nada nuevo, termina en un par de minutos sin cambiar nada. También se puede correr a mano desde la pestaña **Actions** del repositorio (botón *Run workflow*) o, en tu computadora, con `uv run argentina-afip-update`.

> **Si la actualización se frena por códigos nuevos:** cuando en un mes más del 0,1% de las filas trae un código (aduana, país, moneda, unidad o medio de transporte) que no está en los catálogos de `docs/`, la actualización se detiene antes de publicar, para no sumar datos con esos campos vacíos. Hay que actualizar el catálogo correspondiente desde el sitio de ARCA y volver a correrla.

---

## Estructura del proyecto

```
argentina-afip-comex/
├─ argentina_afip_comex/      # Código del proyecto
│  ├─ query.py                # Consultas y exportación (notebook y terminal)
│  ├─ pipeline.py             # Pasos para armar la tabla, mes por mes
│  ├─ update.py               # Actualización con los meses nuevos
│  └─ __main__.py             # Permite consultar con `python -m argentina_afip_comex`
│
├─ notebooks/                 # Los pasos del proceso, numerados
│  ├─ 0.0-collect-data.ipynb
│  ├─ 0.2-convert-parquet.ipynb
│  ├─ 0.3-reshape-data.ipynb
│  ├─ 0.4-decode-data.ipynb
│  └─ 0.5-query-data.ipynb
│
├─ data/
│  ├─ raw/                    # Zips originales de ARCA, por año
│  ├─ interim/                # Archivos intermedios, por mes
│  ├─ processed/              # Tabla final, lista para consultar
│  └─ manifest.json           # Registro de meses procesados
│
├─ docs/                      # Catálogos oficiales de ARCA (anexos) y especificación de los archivos
├─ .github/workflows/         # Actualización automática mensual
├─ outputs/tables/            # Resultados de las consultas
├─ pyproject.toml             # Librerías del proyecto
└─ README.md
```

---

## Fuentes

- Información agregada de comercio exterior, ARCA (ex AFIP): https://www.afip.gob.ar/operadoresComercioExterior/informacionAgregada/informacion-agregada.asp
- Especificación de los archivos: [`docs/Procedimiento-descarga-y-lectura-archivos-de-ComExAFIP-2018.pdf`](docs/Procedimiento-descarga-y-lectura-archivos-de-ComExAFIP-2018.pdf)
- Catálogos de códigos (anexos de ARCA): [`docs/`](docs/)

---

## Licencia

Este proyecto se distribuye bajo licencia [MIT](LICENSE).

---

Este repositorio fue generado con [cookiecutter](https://github.com/fer-aguirre/cookiecutter-data-analysis-lite).
