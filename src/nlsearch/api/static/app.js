/** NL Search UI — async consumer of POST /v1/search */

const $ = (sel) => document.querySelector(sel);

let sessionId = null;

function setStatus(message, kind = "") {
  const el = $("#status");
  el.textContent = message;
  el.className = `status ${kind}`.trim();
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function isPlainObject(v) {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function flattenValue(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function tableFromObjects(rows, caption) {
  if (!rows?.length) return `<p class="empty">No ${caption || "rows"}.</p>`;
  const keys = [...new Set(rows.flatMap((r) => Object.keys(r || {})))];
  if (!keys.length) return `<p class="empty">Empty ${caption || "rows"}.</p>`;

  const thead = keys.map((k) => `<th>${escapeHtml(k)}</th>`).join("");
  const tbody = rows
    .map((row) => {
      const cells = keys
        .map((k) => `<td>${escapeHtml(flattenValue(row?.[k]))}</td>`)
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");

  return `<table class="data-table"><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table>`;
}

function kvTable(obj) {
  if (!obj || !Object.keys(obj).length) return `<p class="empty">None.</p>`;
  const rows = Object.entries(obj)
    .map(
      ([k, v]) =>
        `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(flattenValue(v))}</td></tr>`
    )
    .join("");
  return `<table class="kv-table data-table"><tbody>${rows}</tbody></table>`;
}

function section(title, bodyHtml, badge = "") {
  const badgeHtml = badge ? `<span class="badge">${escapeHtml(badge)}</span>` : "";
  return `
    <section class="result-section">
      <header><h3>${escapeHtml(title)}</h3>${badgeHtml}</header>
      <div class="body">${bodyHtml}</div>
    </section>`;
}

function normalizeRows(rows) {
  if (!Array.isArray(rows) || !rows.length) return [];
  return rows.map((row) => {
    if (isPlainObject(row)) return row;
    if (Array.isArray(row)) {
      const obj = {};
      row.forEach((val, i) => {
        obj[`col_${i}`] = val;
      });
      return obj;
    }
    return { value: row };
  });
}

function renderIntent(intent) {
  if (!intent) return section("Intent", `<p class="empty">No intent returned.</p>`);

  const parts = [];
  parts.push(section("Intent — overview", kvTable({
    result_type: intent.result_type,
    mode: intent.mode,
    limit: intent.limit,
    semantic_query: intent.semantic_query,
    license_notice: intent.license_notice,
  })));

  if (intent.filters?.length) {
    parts.push(section("Intent — filters", tableFromObjects(intent.filters, "filters"), String(intent.filters.length)));
  }

  if (intent.sort?.length) {
    parts.push(section("Intent — sort", tableFromObjects(intent.sort, "sort")));
  }

  if (intent.assumptions?.length) {
    parts.push(
      section(
        "Intent — assumptions",
        `<ul>${intent.assumptions.map((a) => `<li>${escapeHtml(a)}</li>`).join("")}</ul>`
      )
    );
  }

  if (intent.default_exclusions_applied?.length) {
    parts.push(
      section(
        "Intent — default exclusions",
        `<ul>${intent.default_exclusions_applied.map((a) => `<li>${escapeHtml(a)}</li>`).join("")}</ul>`
      )
    );
  }

  if (intent.dropped_constraints?.length) {
    parts.push(
      section(
        "Intent — dropped constraints",
        `<ul>${intent.dropped_constraints.map((a) => `<li>${escapeHtml(a)}</li>`).join("")}</ul>`
      )
    );
  }

  if (intent.geo) {
    parts.push(section("Intent — geo", kvTable(intent.geo)));
  }

  if (intent.aggregation) {
    parts.push(section("Intent — aggregation", kvTable(intent.aggregation)));
  }

  return parts.join("");
}

function renderResults(data) {
  const container = $("#results");
  const sections = [];

  if (data.no_coverage) {
    sections.push(
      section("No coverage", kvTable(data.no_coverage), data.no_coverage.code || "blocked")
    );
  }

  sections.push(
    section(
      "Summary",
      kvTable({
        session_id: data.session_id,
        row_count: data.row_count,
        intent_source: data.intent_source,
        intent_mode: data.intent_mode,
        llm_used: data.llm_used,
        requires_clarification: data.requires_clarification,
      })
    )
  );

  if (data.explanation) {
    sections.push(section("Explanation", `<div class="text-block">${escapeHtml(data.explanation)}</div>`));
  }

  if (data.expression) {
    sections.push(section("Expression", `<pre class="code">${escapeHtml(data.expression)}</pre>`));
  }

  if (data.intent_warnings?.length) {
    sections.push(
      section(
        "Warnings",
        `<ul>${data.intent_warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("")}</ul>`,
        String(data.intent_warnings.length)
      )
    );
  }

  if (data.execution && Object.keys(data.execution).length) {
    sections.push(section("Execution", kvTable(data.execution)));
  }

  if (data.latency_ms) {
    sections.push(section("Latency (ms)", kvTable(data.latency_ms)));
  }

  sections.push(renderIntent(data.intent));

  if (data.sql) {
    sections.push(section("SQL", `<pre class="code">${escapeHtml(data.sql)}</pre>`));
  }

  const rows = normalizeRows(data.rows);
  sections.push(
    section("Query results", tableFromObjects(rows, "results"), `${data.row_count ?? rows.length} rows`)
  );

  sections.push(
    section("Raw JSON", `<pre class="json">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`)
  );

  container.innerHTML = sections.join("");
}

function buildPayload() {
  const query = $("#query").value.trim();
  const payload = {
    query,
    execute: $("#execute").checked,
    use_llm: $("#useLlm").checked,
    intent_mode: $("#intentMode").value,
  };

  if (sessionId) payload.session_id = sessionId;

  const userRegion = $("#userRegion").value.trim();
  if (userRegion) {
    payload.context = { user_region: userRegion };
  }

  return payload;
}

async function runSearch() {
  const query = $("#query").value.trim();
  if (!query) {
    setStatus("Enter a search query.", "error");
    return;
  }

  const btn = $("#searchBtn");
  btn.disabled = true;
  setStatus("Searching…");

  try {
    const response = await fetch("/v1/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildPayload()),
    });

    const data = await response.json();

    if (!response.ok) {
      const detail = data.detail || response.statusText;
      setStatus(`Error ${response.status}: ${detail}`, "error");
      $("#results").innerHTML = section(
        "Error",
        `<pre class="json">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`
      );
      return;
    }

    sessionId = data.session_id || sessionId;
    if (sessionId) $("#sessionHint").textContent = `Session: ${sessionId.slice(0, 8)}…`;

    renderResults(data);
    const ms = data.latency_ms?.total_ms;
    setStatus(
      ms != null
        ? `Done — ${data.row_count ?? 0} rows in ${Math.round(ms)} ms`
        : `Done — ${data.row_count ?? 0} rows`,
      "ok"
    );
  } catch (err) {
    setStatus(`Request failed: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
  }
}

async function clearSession() {
  if (!sessionId) {
    setStatus("No active session.", "error");
    return;
  }

  try {
    await fetch(`/v1/session/${sessionId}`, { method: "DELETE" });
    sessionId = null;
    $("#sessionHint").textContent = "";
    setStatus("Session cleared.", "ok");
  } catch (err) {
    setStatus(`Clear failed: ${err.message}`, "error");
  }
}

function init() {
  $("#searchBtn").addEventListener("click", runSearch);
  $("#clearSessionBtn").addEventListener("click", clearSession);
  $("#query").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      runSearch();
    }
  });
}

document.addEventListener("DOMContentLoaded", init);
