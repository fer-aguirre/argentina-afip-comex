---
title: Consulta de importaciones
---

# Consulta de importaciones

<div class="dek">Busca declaraciones de importación por código NCM, nombre del importador o ambos, filtra por año y descarga los resultados en CSV.</div>

```js
const ROW_LIMIT = 10000;
```

```js
const db = await DuckDBClient.of({
  importaciones: FileAttachment("data/importaciones_2019-2026_decoded.parquet")
});
```

```js
const yearRows = await db.query(
  "SELECT DISTINCT CAST(substr(FECHA, 1, 4) AS INTEGER) AS anio FROM importaciones ORDER BY anio"
);
const availableYears = yearRows.toArray().map((r) => r.anio);
```

## Filtros

Elige qué campo(s) buscar. Al escribir aparecen sugerencias tomadas directamente de los datos; selecciónalas con la casilla para agregarlas a la búsqueda.

```js
const filters = view((() => {
  const container = html`<div class="filters-panel">
    <div class="mode-row">
      <label><input type="radio" name="mode" value="ncm" checked /> NCM</label>
      <label><input type="radio" name="mode" value="importador" /> Importador</label>
      <label><input type="radio" name="mode" value="ambos" /> Ambos</label>
    </div>
    <div class="filter-section" data-section="ncm">
      <input type="text" inputmode="numeric" autocomplete="off" placeholder="Buscar código NCM (solo números)…" />
      <div class="field-hint"></div>
      <div class="chips"></div>
      <div class="suggestions"></div>
    </div>
    <div class="filter-section" data-section="importador" style="display:none">
      <input type="text" autocomplete="off" placeholder="Buscar nombre de importador…" />
      <div class="field-hint"></div>
      <div class="chips"></div>
      <div class="suggestions"></div>
    </div>
  </div>`;

  const ncmSection = container.querySelector('[data-section="ncm"]');
  const importadorSection = container.querySelector('[data-section="importador"]');
  const modeInputs = [...container.querySelectorAll('input[name="mode"]')];

  // ncm/importador hold the *selected* values; independent from whatever
  // is currently rendered in the suggestion box, so picks survive re-search.
  const state = { mode: "ncm", ncm: new Set(), importador: new Set() };

  const debounce = (fn, delay) => {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), delay);
    };
  };

  const emit = () => {
    container.value = {
      mode: state.mode,
      ncm: [...state.ncm],
      importador: [...state.importador]
    };
    container.dispatchEvent(new Event("input", { bubbles: true }));
  };

  function setupSection({ section, key, queryFn, minChars = 0 }) {
    const input = section.querySelector("input");
    const suggestionBox = section.querySelector(".suggestions");
    const chipBox = section.querySelector(".chips");
    const hint = section.querySelector(".field-hint");
    let lastValues = [];

    function renderMessage(text) {
      suggestionBox.innerHTML = "";
      suggestionBox.appendChild(html`<div class="empty">${text}</div>`);
    }

    function renderChips() {
      chipBox.innerHTML = "";
      for (const value of state[key]) {
        const chip = html`<span class="chip">${value} <button type="button" aria-label="Quitar">×</button></span>`;
        chip.querySelector("button").addEventListener("click", () => {
          state[key].delete(value);
          renderChips();
          renderSuggestions(lastValues);
          emit();
        });
        chipBox.appendChild(chip);
      }
    }

    function renderSuggestions(values) {
      lastValues = values;
      suggestionBox.innerHTML = "";
      if (values.length === 0) {
        renderMessage("Sin coincidencias.");
        return;
      }
      for (const value of values) {
        const row = html`<div class="suggestion-row">
          <label><input type="checkbox" ${state[key].has(value) ? "checked" : ""} /> ${value}</label>
        </div>`;
        row.querySelector("input").addEventListener("change", (e) => {
          if (e.target.checked) state[key].add(value);
          else state[key].delete(value);
          renderChips();
          emit();
        });
        suggestionBox.appendChild(row);
      }
    }

    const runSearch = debounce(async () => {
      const query = input.value.trim();
      if (query.length < minChars) {
        renderMessage(`Escribe al menos ${minChars} caracteres para buscar.`);
        return;
      }
      const values = await queryFn(query);
      renderSuggestions(values);
    }, 300);

    input.addEventListener("input", runSearch);
    renderMessage(minChars > 0 ? `Escribe al menos ${minChars} caracteres para buscar.` : "Escribe un código para buscar.");

    return { renderChips };
  }

  const ncmControls = setupSection({
    section: ncmSection,
    key: "ncm",
    minChars: 1,
    queryFn: async (rawQuery) => {
      const input = ncmSection.querySelector("input");
      const cleaned = rawQuery.replace(/[^0-9.]/g, "");
      const hint = ncmSection.querySelector(".field-hint");
      if (cleaned !== input.value) input.value = cleaned;
      if (cleaned !== rawQuery) {
        hint.textContent = "Solo se permiten números (y puntos).";
        hint.classList.add("error");
      } else {
        hint.textContent = "";
        hint.classList.remove("error");
      }
      if (cleaned.length === 0) return [];
      const rows = await db.query(
        "SELECT DISTINCT NCM FROM importaciones WHERE NCM LIKE ? ORDER BY NCM LIMIT 30",
        [`${cleaned}%`]
      );
      return rows.toArray().map((r) => r.NCM);
    }
  });

  const importadorControls = setupSection({
    section: importadorSection,
    key: "importador",
    minChars: 2,
    queryFn: async (query) => {
      const rows = await db.query(
        "SELECT DISTINCT IMPORTADOR FROM importaciones WHERE IMPORTADOR ILIKE ? ORDER BY IMPORTADOR LIMIT 30",
        [`%${query}%`]
      );
      return rows.toArray().map((r) => r.IMPORTADOR);
    }
  });

  for (const radio of modeInputs) {
    radio.addEventListener("change", (e) => {
      state.mode = e.target.value;
      const showNcm = state.mode !== "importador";
      const showImportador = state.mode !== "ncm";
      // Clear selections in whichever section becomes hidden, so there is
      // never an invisible filter silently narrowing the results.
      if (!showNcm && state.ncm.size > 0) {
        state.ncm.clear();
        ncmControls.renderChips();
      }
      if (!showImportador && state.importador.size > 0) {
        state.importador.clear();
        importadorControls.renderChips();
      }
      ncmSection.style.display = showNcm ? "block" : "none";
      importadorSection.style.display = showImportador ? "block" : "none";
      emit();
    });
  }

  emit();
  return container;
})());
```

```js
const selectedYears = view(Inputs.checkbox(availableYears, {
  value: availableYears,
  format: (d) => String(d),
  label: "Años"
}));
```

```js
function buildFilterQuery(selection, years) {
  const params = [];
  const clauses = [];

  if (years.length > 0) {
    clauses.push(`substr(FECHA, 1, 4) IN (${years.map(() => "?").join(", ")})`);
    for (const y of years) params.push(String(y));
  }

  if (selection.ncm.length > 0) {
    clauses.push(`(${selection.ncm.map(() => "NCM LIKE ?").join(" OR ")})`);
    for (const code of selection.ncm) params.push(`${code}%`);
  }

  if (selection.importador.length > 0) {
    clauses.push(`(${selection.importador.map(() => "IMPORTADOR ILIKE ?").join(" OR ")})`);
    for (const name of selection.importador) params.push(`%${name}%`);
  }

  const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
  const query = `
    SELECT *,
      CAST(substr(FECHA, 1, 4) AS INTEGER) AS "AÑO",
      CAST(substr(FECHA, 5, 2) AS INTEGER) AS "MES"
    FROM importaciones
    ${where}
    ORDER BY FECHA DESC
    LIMIT ${ROW_LIMIT}
  `;

  return { query, params };
}

function toCSV(rows) {
  if (rows.length === 0) return "";
  const columns = Object.keys(rows[0]);
  const escape = (value) => {
    if (value == null) return "";
    const text = String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const lines = [columns.join(",")];
  for (const row of rows) lines.push(columns.map((c) => escape(row[c])).join(","));
  return lines.join("\n");
}

function buildExportFilename(selection, years) {
  const parts = [];
  if (selection.importador.length > 0) {
    parts.push(selection.importador.map((n) => n.trim().replace(/\s+/g, "_").toLowerCase()).join("-"));
  }
  if (selection.ncm.length > 0) parts.push(selection.ncm.join("-"));
  const prefix = parts.length > 0 ? parts.join("_") : "consulta";

  const sortedYears = [...years].sort((a, b) => a - b);
  const yearSuffix =
    sortedYears.length === 0
      ? ""
      : sortedYears[0] === sortedYears[sortedYears.length - 1]
        ? `_${sortedYears[0]}`
        : `_${sortedYears[0]}-${sortedYears[sortedYears.length - 1]}`;

  return `${prefix}${yearSuffix}.csv`;
}
```

```js
let resultRows = [];
let truncated = false;
if (filters.ncm.length > 0 || filters.importador.length > 0) {
  const { query, params } = buildFilterQuery(filters, selectedYears);
  const table = await db.query(query, params);
  resultRows = table.toArray();
  truncated = resultRows.length === ROW_LIMIT;
}
```

```js
const downloadButton = html`<button class="download-button">Descargar CSV</button>`;
downloadButton.disabled = resultRows.length === 0;
downloadButton.addEventListener("click", () => {
  const blob = new Blob([toCSV(resultRows)], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = buildExportFilename(filters, selectedYears);
  a.click();
  URL.revokeObjectURL(url);
});

display(html`<div class="results-toolbar"><h2>Resultados</h2>${downloadButton}</div>`);
```

```js
const numericColumns = new Set([
  "CANTIDAD_UNIDAD_MEDIDA",
  "FOB_UNITARIO_USD",
  "FOB_TOTAL_USD",
  "MONTO_TRIBUTADO_TOTAL",
  "AÑO",
  "MES"
]);

function formatCell(value, column) {
  if (value == null) return "";
  if (numericColumns.has(column) && typeof value === "number") {
    return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 }).format(value);
  }
  return String(value);
}

if (resultRows.length === 0) {
  display(html`<p class="status-line">${
    filters.ncm.length === 0 && filters.importador.length === 0
      ? "Selecciona al menos un NCM o un importador para comenzar."
      : "No se encontraron resultados con estos filtros."
  }</p>`);
} else {
  const columns = Object.keys(resultRows[0]);
  display(html`<p class="status-line">${resultRows.length.toLocaleString("es-AR")} fila${resultRows.length === 1 ? "" : "s"} encontrada${resultRows.length === 1 ? "" : "s"}${truncated ? ` (mostrando las primeras ${ROW_LIMIT.toLocaleString("es-AR")})` : ""}.</p>`);
  display(html`<div class="data-table-wrap">
    <table class="data-table">
      <thead><tr>${columns.map((c) => html`<th>${c}</th>`)}</tr></thead>
      <tbody>
        ${resultRows.map(
          (row) => html`<tr>${columns.map((c) => html`<td class="${numericColumns.has(c) ? "numeric" : ""}">${formatCell(row[c], c)}</td>`)}</tr>`
        )}
      </tbody>
    </table>
  </div>`);
}
```
