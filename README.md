# Argentina AFIP Comercio Exterior

Análisis de datos de AFIP (ARCA) para comercio exterior en Argentina.

Creado por: Fernanda Aguirre Ruiz

---

## ¿Qué es esto?

ARCA (ex AFIP) publica cada mes información agregada de las declaraciones de importación de Argentina: quién importó qué producto, por qué monto, desde qué país, por qué aduana, etc. Esos archivos crudos son difíciles de usar directamente: vienen en zips mensuales con reportes de texto de ancho fijo, con códigos internos en vez de nombres y una fila repetida por cada concepto tributario de la declaración.

Este proyecto toma esos archivos crudos y arma **una sola tabla limpia** de importaciones (desde enero 2019, más de 43 millones de filas, una por ítem de declaración, [actualizada todos los meses](#actualización-automática)), con aduanas, países, monedas, unidades y medios de transporte traducidos a su nombre, lista para consultar sin necesidad de saber programar.

La tabla se actualiza sola: todos los meses, un proceso automático revisa si ARCA publicó datos nuevos y, si los hay, procesa solo esos meses y publica la versión actualizada. Ver [Actualización automática](#actualización-automática).

> Por ahora solo incluye **importaciones**. Los años 2017-2018 quedan afuera porque ARCA los publica en un formato distinto, incompatible con el resto.

---

## Por dónde empezar

**Si solo querés buscar datos (sin programar):**
Abrí [`notebooks/0.5-query-data.ipynb`](notebooks/0.5-query-data.ipynb) en Jupyter o VS Code, cambiá los valores de la celda de configuración (años, importador, código NCM, formato) y ejecutá. El resultado se muestra en el cuaderno y se guarda en `outputs/tables/`.

**Si preferís la terminal:**
```bash
uv run argentina-afip-query --years 2024 --ncm 2701 --importador "acme"
```
Ver todas las opciones con `--help`. Más ejemplos en [Consultar los datos](#consultar-los-datos) más abajo.

**Si querés entender o modificar cómo se arma el dataset:**
Mirá [El pipeline de datos](#el-pipeline-de-datos): son notebooks numerados que se corren en orden. Y [Actualización automática](#actualización-automática) para cómo se suman los meses nuevos.

---

## Instalación

Este proyecto usa [`uv`](https://docs.astral.sh/uv/) para manejar Python y las dependencias (ya viene todo definido en `pyproject.toml`/`uv.lock`, no hay que instalar nada a mano). Si todavía no tenés `uv`, seguí su [guía de instalación](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/fer-aguirre/argentina-afip-comex.git
cd argentina-afip-comex
uv sync
```

Eso crea un entorno virtual (`.venv`) con todo lo necesario, incluido el comando `argentina-afip-query`. Todos los comandos de este README se corren desde la carpeta del proyecto.

---

## Conseguir los datos

La tabla final (`importaciones_decoded.parquet`, ~900 MB) se descarga sola la primera vez que hace falta — no hay que hacer nada a mano. En cuanto corrés una consulta (notebook `0.5` o la terminal) y el archivo todavía no está en `data/processed/`, se baja automáticamente desde el [release más reciente](https://github.com/fer-aguirre/argentina-afip-comex/releases/latest) del repositorio (con barra de progreso), y queda guardado ahí para las próximas veces.

Si en cambio querés armar la tabla por tu cuenta desde cero, corré los notebooks del [pipeline](#el-pipeline-de-datos) en orden, empezando por `0.0`, que descarga los zips mensuales desde el sitio de ARCA. Ojo: el proceso completo necesita unos 30 GB libres en disco (zips originales, archivos intermedios y tablas finales).

> **Para tener los meses más recientes:** si ya descargaste la tabla antes, tu copia no se actualiza sola, porque el archivo local ya existe. Borrá `data/processed/importaciones_decoded.parquet` y volvé a correr una consulta: se descarga la versión más nueva. Podés ver hasta qué mes llega cada versión en las notas del [release más reciente](https://github.com/fer-aguirre/argentina-afip-comex/releases/latest) o en [`data/manifest.json`](data/manifest.json).

---

## El pipeline de datos

Notebooks pensados para correrse en orden (cada uno depende de los archivos que arma el anterior). Todos trabajan **mes por mes**: cada paso guarda un archivo por mes y saltea los meses que ya procesó, así que volver a correrlos solo procesa lo que falta. La lógica vive en [`argentina_afip_comex/pipeline.py`](argentina_afip_comex/pipeline.py), la misma que usa la [actualización automática](#actualización-automática).

| Notebook | Qué hace | Entrada | Salida |
|---|---|---|---|
| [`0.0-collect-data.ipynb`](notebooks/0.0-collect-data.ipynb) | Descarga los zips mensuales desde el sitio de ARCA (desde 2019). | Sitio de ARCA | `data/raw/<año>/<aaaamm>.zip` |
| [`0.2-convert-parquet.ipynb`](notebooks/0.2-convert-parquet.ipynb) | Convierte el reporte de texto de cada mes a parquet. | `data/raw/<año>/<aaaamm>.zip` | `data/interim/<año>/<aaaamm>/impo_<aaaamm>.parquet` |
| [`0.3-reshape-data.ipynb`](notebooks/0.3-reshape-data.ipynb) | Junta las filas repetidas por concepto tributario en una sola fila por ítem de declaración, sumando los montos tributados. | `impo_<aaaamm>.parquet` | `impo_<aaaamm>_reshaped.parquet` (misma carpeta) |
| [`0.4-decode-data.ipynb`](notebooks/0.4-decode-data.ipynb) | Traduce los códigos de ARCA (aduana, país, moneda, unidad, transporte) a su nombre usando los catálogos oficiales de `docs/`, y une todos los meses en la tabla final. | `impo_<aaaamm>_reshaped.parquet` | `data/processed/months/importaciones_<aaaamm>_decoded.parquet` y `data/processed/importaciones_decoded.parquet` |
| [`0.5-query-data.ipynb`](notebooks/0.5-query-data.ipynb) | Consulta la tabla final por año, importador y/o NCM, y exporta el resultado. | `importaciones_decoded.parquet` | CSV/Excel/Parquet en `outputs/tables/` |

Cada notebook explica en su primera celda qué hace y las decisiones detrás de cada paso.

---

## Actualización automática

ARCA publica cada mes nuevo el día 1 del mes siguiente. Un workflow de GitHub Actions ([`.github/workflows/update-data.yml`](.github/workflows/update-data.yml)) revisa del **1 al 7 de cada mes a las 09:14 (hora de Argentina)** si hay meses nuevos y, si los hay:

1. Descarga y procesa **solo esos meses** (los ya procesados nunca se vuelven a descargar ni a procesar).
2. Los agrega a la tabla final y publica un [release](https://github.com/fer-aguirre/argentina-afip-comex/releases/latest) nuevo, con la fecha de la actualización como nombre (ej. `v2026.10.09`). Se conserva solo el release más reciente.
3. Registra los meses agregados en [`data/manifest.json`](data/manifest.json), que lista cada mes procesado con su cantidad de filas y la fecha en que se procesó.

Si no hay nada nuevo, termina en un par de minutos sin cambiar nada. También se puede correr a mano desde la pestaña **Actions** del repositorio (botón *Run workflow*), o en local con `uv run argentina-afip-update`.

> **Si la actualización falla** por códigos nuevos: si en un mes más del 0,1% de las filas trae un código (aduana, país, moneda, unidad o medio de transporte) que no está en los catálogos de `docs/`, la actualización se detiene antes de publicar, para no sumar datos con esos campos vacíos. Hay que actualizar el catálogo correspondiente desde el sitio de ARCA y volver a correrla.

---

## Consultar los datos

La lógica de consulta vive en [`argentina_afip_comex/query.py`](argentina_afip_comex/query.py) y funciona igual desde un notebook o desde la terminal.

**Filtros disponibles** (al menos `importador` o `ncm` es obligatorio, para no recorrer las ~43 millones de filas sin acotar):

| Filtro | Qué es | Ejemplo |
|---|---|---|
| `years` | Año o lista de años | `2024` / `[2023, 2024, 2025]` |
| `importador` *(opcional)* | Nombre del importador. Busca coincidencia parcial, sin distinguir mayúsculas/minúsculas; podés escribir puntos o paréntesis tal cual (ej. `"s.a."`). Cuanto más específico, mejor: un término corto como `"sa"` puede devolver miles de resultados. | `"acme"` |
| `ncm` *(opcional)* | Código NCM o prefijo. Los puntos son opcionales: `84.20` = `8420`, y `8420.10.00` = `84201000`. | `"2701"` |

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
Por defecto exporta un CSV al directorio donde estás parado/a; usá `--output`/`-o` para elegir otra carpeta (se crea si no existe) y `--formato`/`-f` para elegir entre `csv`, `xlsx` o `parquet`. Ver todas las opciones con `--help`.

> **¿CSV o Excel?** El CSV es el formato por defecto porque no tiene límite de filas. Excel admite como máximo 1.048.576 filas por hoja, así que una búsqueda amplia (por ejemplo, un capítulo NCM entero en varios años) puede no entrar en un `.xlsx`.

> **En Windows**, si `uv run argentina-afip-query` falla con un error de que una directiva bloqueó el archivo, usá el mismo comando así: `uv run python -m argentina_afip_comex --years 2024 --ncm 2701`.

El resultado de la consulta trae las columnas del [diccionario de datos](#diccionario-de-datos), más `AÑO` y `MES` (números, derivados de `FECHA`) para filtrar o agrupar más fácil.

---

## Diccionario de datos

Columnas de `importaciones_decoded.parquet`. La columna "Catálogo" indica qué anexo de [`docs/`](docs/) se usó para traducir el código a su nombre.

| Columna | Tipo | Catálogo | Descripción |
|---|---|---|---|
| ADUANA | texto | ANEXOIV | Aduana donde se registró la importación |
| DESTINACION | texto | — | Número de registro de la declaración de importación |
| NUM_ITEM | texto | — | Número de ítem dentro de la declaración |
| FECHA | texto | — | Mes de oficialización (formato AAAAMM, ej. `202401`) |
| IMPORTADOR | texto | — | Nombre completo del importador |
| MEDIO_TRANSPORTE | texto | ANEXOV | Medio de transporte (ej. CAMION, AVION, ACUATICO) |
| UNIDAD_MEDIDA | texto | ANEXOXV | Unidad de medida (ej. TONELADA, UNIDAD, KILOGRAMO) |
| CANTIDAD_UNIDAD_MEDIDA | número | — | Cantidad en la unidad de medida especificada |
| FOB_UNITARIO_USD | número | — | Valor FOB/CIF unitario en USD |
| FOB_TOTAL_USD | número | — | Valor FOB/CIF total en USD |
| DIVISA | texto | ANEXOXI | Divisa (ej. DOLAR, EURO, GUARANI) |
| PAIS_ORIGEN | texto | ANEXOVII | País de origen |
| PAIS_PROCEDENCIA | texto | ANEXOVII | País de procedencia |
| NCM | texto | — | Posición arancelaria del Mercosur, con puntos (ej. `8420.10.90`). No se traduce: el nomenclador es un catálogo externo |
| MONTO_TRIBUTADO_TOTAL | número | — | Suma de todos los montos tributados del ítem de declaración (ver `0.3-reshape-data.ipynb`) |

La especificación oficial de ARCA para estos archivos está en [`docs/Procedimiento-descarga-y-lectura-archivos-de-ComExAFIP-2018.pdf`](docs/Procedimiento-descarga-y-lectura-archivos-de-ComExAFIP-2018.pdf).

---

## Estructura del proyecto

```
argentina-afip-comex/
├─ argentina_afip_comex/      # Paquete de Python del proyecto
│  ├─ query.py                # Consulta y exportación del dataset (notebook + terminal)
│  ├─ pipeline.py             # Pasos del pipeline, mes por mes (los usan los notebooks y la actualización)
│  ├─ update.py               # Actualización con los meses nuevos (`argentina-afip-update`)
│  └─ __main__.py             # Permite correr la consulta con `python -m argentina_afip_comex`
│
├─ notebooks/                 # El pipeline, en pasos numerados (ver más arriba)
│  ├─ 0.0-collect-data.ipynb
│  ├─ 0.2-convert-parquet.ipynb
│  ├─ 0.3-reshape-data.ipynb
│  ├─ 0.4-decode-data.ipynb
│  └─ 0.5-query-data.ipynb
│
├─ data/
│  ├─ raw/                    # Zips mensuales originales de ARCA, por año
│  ├─ interim/                # Archivos intermedios de 0.2 y 0.3 (por mes)
│  ├─ processed/              # Tabla final, lista para consultar
│  │  └─ months/              # Un archivo decodificado por mes (0.4)
│  └─ manifest.json           # Meses ya procesados (lo actualiza el workflow)
│
├─ docs/                      # Catálogos oficiales de ARCA (ANEXOs) y especificación de los archivos
│
├─ .github/workflows/
│  └─ update-data.yml         # Actualización automática mensual
│
├─ outputs/
│  ├─ tables/                 # Exports de consultas desde los notebooks
│  └─ figures/                # Gráficos, si los hay
│
├─ pyproject.toml             # Dependencias del proyecto
└─ README.md
```

---

## Fuente de los datos

Información agregada de comercio exterior publicada por ARCA (ex AFIP): https://www.afip.gob.ar/operadoresComercioExterior/informacionAgregada/informacion-agregada.asp

---

## Licencia

Este proyecto se distribuye bajo licencia [MIT](/LICENSE).

---

Este repositorio fue generado con [cookiecutter](https://github.com/fer-aguirre/cookiecutter-data-analysis-lite).
