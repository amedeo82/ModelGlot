(() => {
  "use strict";

  const INVALID_REPORT = "Invalid token optimization report";
  const STATE_LABELS = {
    available: "Available",
    not_installed: "Not installed",
    timeout: "Timed out",
    invalid_output: "Invalid output",
    error: "Unavailable",
  };
  const TOOLS = {
    rtk: {
      cardId: "tokenOptimizationRtk",
      stateId: "tokenOptimizationRtkState",
      source: "rtk gain --format json",
      counters: ["tokens_saved", "total_commands", "tokens_before", "tokens_after", "savings_percent"],
    },
    headroom: {
      cardId: "tokenOptimizationHeadroom",
      stateId: "tokenOptimizationHeadroomState",
      source: "headroom savings --json",
      counters: ["tokens_saved", "calls", "tokens_before", "savings_percent"],
    },
  };
  const byId = (id) => document.getElementById(id);
  const root = byId("tokenOptimizationRoot");
  const refreshButton = byId("tokenOptimizationRefresh");
  let requestApi = null;
  let active = false;
  let flight = null;
  let requestController = null;
  let latestRequest = 0;
  let loading = false;
  let report = null;
  let errorMessage = "";
  let usageReport = null;
  let usageError = "";
  let usageLoading = false;
  let usageFlight = null;
  let usageController = null;
  let usageRequest = 0;

  function invalidReport() {
    throw new Error(INVALID_REPORT);
  }

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function nullableString(value) {
    if (value === undefined || value === null) return null;
    if (typeof value !== "string") invalidReport();
    return value.trim() || null;
  }

  function counter(value, percentage = false) {
    if (value === undefined || value === null) return null;
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) invalidReport();
    if (percentage ? false : !Number.isSafeInteger(value)) invalidReport();
    return value;
  }

  function normalizeDaily(value) {
    if (value === undefined || value === null) return [];
    if (!Array.isArray(value) || value.length > 31) invalidReport();
    return value.map((row) => {
      if (!isRecord(row) || typeof row.date !== "string" || !Number.isFinite(Date.parse(`${row.date}T00:00:00Z`)) || row.basis !== "tool_reported") invalidReport();
      return {
        date: row.date,
        tokens_saved: counter(row.tokens_saved),
        tokens_before: counter(row.tokens_before),
        tokens_after: counter(row.tokens_after),
        savings_percent: counter(row.savings_percent, true),
      };
    });
  }

  function normalizeTool(tool, value) {
    if (!isRecord(value) || !Object.prototype.hasOwnProperty.call(STATE_LABELS, value.state)) invalidReport();
    if (value.source !== TOOLS[tool].source || value.basis !== "tool_reported") invalidReport();
    const normalized = {
      state: value.state,
      version: nullableString(value.version),
      source: value.source,
      basis: value.basis,
      message: nullableString(value.message),
    };
    TOOLS[tool].counters.forEach((name) => {
      normalized[name] = counter(value[name], name === "savings_percent");
    });
    if (tool === "rtk") normalized.daily = normalizeDaily(value.daily);
    return normalized;
  }

  function normalizeExternal(payload) {
    if (!isRecord(payload) || payload.schema_version !== 1 || !isRecord(payload.optimizations)) invalidReport();
    if (typeof payload.generated_at !== "string" || !Number.isFinite(Date.parse(payload.generated_at))) invalidReport();
    return {
      schema_version: 1,
      generated_at: payload.generated_at,
      optimizations: {
        rtk: normalizeTool("rtk", payload.optimizations.rtk),
        headroom: normalizeTool("headroom", payload.optimizations.headroom),
      },
    };
  }

  function formatCounter(value, percentage = false) {
    if (value === null) return "Not reported";
    const formatted = value.toLocaleString("en-US", { maximumFractionDigits: 2 });
    return percentage ? `${formatted}%` : formatted;
  }

  function fallbackMessage(tool, toolReport) {
    if (toolReport.state === "available" && toolReport.tokens_saved === 0) {
      return `${tool === "rtk" ? "RTK" : "Headroom"} reported zero savings. Zero counters do not prove inactivity.`;
    }
    const label = tool === "rtk" ? "RTK" : "Headroom";
    const messages = {
      not_installed: `${label} is not installed or is not available on PATH.`,
      timeout: `${label} did not respond before the collection timeout. Try Refresh.`,
      invalid_output: `${label} returned a report that could not be read. Try Refresh.`,
      error: `${label} report is unavailable. Try Refresh.`,
    };
    return messages[toolReport.state] || "";
  }

  function renderTool(tool, toolReport) {
    const definition = TOOLS[tool];
    const card = byId(definition.cardId);
    const state = byId(definition.stateId);
    card.dataset.state = toolReport.state;
    state.dataset.state = toolReport.state;
    state.textContent = STATE_LABELS[toolReport.state];
    ["version", "source", "basis"].forEach((field) => {
      card.querySelector(`[data-field="${field}"]`).textContent = toolReport[field] || "Not reported";
    });
    definition.counters.forEach((name) => {
      card.querySelector(`[data-counter="${name}"]`).textContent = formatCounter(
        toolReport[name],
        name === "savings_percent",
      );
    });
    const message = card.querySelector('[data-field="message"]');
    message.textContent = toolReport.message || fallbackMessage(tool, toolReport);
    message.hidden = !message.textContent;
  }

  function renderRegions() {
    root.dataset.active = String(active);
    root.setAttribute("aria-busy", String(loading));
    refreshButton.disabled = loading;
    refreshButton.textContent = loading ? "Refreshing…" : "Refresh";
    refreshButton.setAttribute("aria-busy", String(loading));
    byId("tokenOptimizationCards").hidden = !report;

    const loadingRegion = byId("tokenOptimizationLoading");
    loadingRegion.hidden = !loading;
    loadingRegion.textContent = report
      ? "Refreshing token optimization reports… Last valid data remains visible."
      : "Loading token optimization reports…";

    const errorRegion = byId("tokenOptimizationError");
    errorRegion.hidden = !errorMessage;
    errorRegion.textContent = errorMessage;

    const hasAvailableReport = report && Object.values(report.optimizations).some(
      (toolReport) => toolReport.state === "available",
    );
    byId("tokenOptimizationEmpty").hidden = loading || Boolean(hasAvailableReport);
  }

  function renderExternal(payload) {
    const normalized = normalizeExternal(payload);
    report = normalized;
    errorMessage = "";
    Object.entries(normalized.optimizations).forEach(([tool, toolReport]) => {
      renderTool(tool, toolReport);
    });
    const generatedAt = byId("tokenOptimizationGeneratedAt");
    generatedAt.dateTime = normalized.generated_at;
    generatedAt.textContent = normalized.generated_at;
    renderRegions();
    renderTrends();
    return normalized;
  }

  function refresh() {
    if (flight) return flight;
    if (typeof requestApi !== "function") {
      errorMessage = "Token optimization is not ready. Reload the Admin page and try again.";
      renderRegions();
      return Promise.resolve(false);
    }

    const request = ++latestRequest;
    const controller = new AbortController();
    requestController = controller;
    loading = true;
    errorMessage = "";
    renderRegions();
    flight = (async () => {
      try {
        const payload = await requestApi("/admin/api/token-optimization", {
          signal: controller.signal,
        });
        if (request !== latestRequest) return false;
        renderExternal(payload);
        return true;
      } catch (error) {
        if (request !== latestRequest) return false;
        const invalid = error instanceof Error && error.message === INVALID_REPORT;
        const detail = invalid
          ? "The server returned an invalid token optimization report."
          : error instanceof Error && error.message
            ? error.message
            : "The report request failed.";
        errorMessage = `Could not refresh token optimization reports. ${detail}${report ? " Last valid data is still shown." : ""}`;
        renderRegions();
        return false;
      } finally {
        if (request === latestRequest) {
          loading = false;
          flight = null;
          requestController = null;
          renderRegions();
        }
      }
    })();
    return flight;
  }

  function setActive(nextActive, request) {
    active = Boolean(nextActive);
    if (typeof request === "function") requestApi = request;
    if (!active && flight) {
      latestRequest += 1;
      requestController?.abort();
      requestController = null;
      flight = null;
      loading = false;
    }
    if (!active && usageFlight) {
      usageRequest += 1;
      usageController?.abort();
      usageController = null;
      usageFlight = null;
      usageLoading = false;
    }
    renderRegions();
    renderUsageRegions();
    if (active) {
      void refreshUsage();
      return refresh();
    }
    return Promise.resolve(false);
  }

  function normalizeUsage(payload) {
    if (!isRecord(payload) || payload.schema_version !== 1 || !Array.isArray(payload.rows)) invalidReport();
    if (typeof payload.generated_at !== "string" || !Number.isFinite(Date.parse(payload.generated_at))) invalidReport();
    return payload;
  }

  function usageQuery() {
    const query = new URLSearchParams();
    query.set("group_by", byId("usageGroupBy").value);
    ["From", "To"].forEach((suffix) => {
      const value = byId(`usage${suffix}`).value;
      if (value) query.set(suffix.toLowerCase(), `${value}Z`);
    });
    return query;
  }

  function cell(row, text) {
    const element = document.createElement("td");
    element.textContent = text;
    row.appendChild(element);
  }

  function formatUsageValue(value, suffix = "") {
    if (value === null || value === undefined) return "Not reported";
    if (typeof value === "number") return `${formatCounter(value)}${suffix}`;
    return String(value);
  }

  function renderUsageRows(rows) {
    const body = byId("usageRows");
    body.replaceChildren();
    rows.forEach((usageRow) => {
      const row = document.createElement("tr");
      [
        usageRow.day || "—",
        usageRow.provider_id || "Unknown",
        usageRow.gateway_model || "—",
        usageRow.provider_model || "—",
        formatUsageValue(usageRow.request_count),
        formatUsageValue(usageRow.successful_count),
        formatUsageValue(usageRow.failed_count),
        formatUsageValue(usageRow.cancelled_count),
        formatUsageValue(usageRow.physical_attempt_count),
        formatUsageValue(usageRow.input_total_tokens),
        formatUsageValue(usageRow.output_tokens),
        formatUsageValue(usageRow.cache_read_tokens),
        formatUsageValue(usageRow.estimated_input_tokens),
      ].forEach((value) => cell(row, value));
      body.appendChild(row);
    });
  }

  function renderContextSection(key, bodyId, summaryId) {
    const section = usageReport?.context?.[key] || { rows: [] };
    const body = byId(bodyId);
    body.replaceChildren();
    (section.rows || []).forEach((sample) => {
      const row = document.createElement("tr");
      const model = [sample.provider_id, sample.provider_model].filter(Boolean).join(" / ") || "Unknown model";
      const values = [
        model,
        formatUsageValue(sample.context_used_tokens),
        formatUsageValue(sample.context_window_tokens),
        sample.utilization_percent === null || sample.utilization_percent === undefined
          ? "Unknown"
          : formatUsageValue(sample.utilization_percent, "%"),
        key === "request_input"
          ? formatUsageValue(sample.sampled_at)
          : sample.stale ? "Stale" : "Current",
      ];
      values.forEach((value) => cell(row, value));
      body.appendChild(row);
    });
    const average = section.average_utilization_percent === null || section.average_utilization_percent === undefined
      ? "unknown" : `${section.average_utilization_percent}%`;
    const maximum = section.maximum_utilization_percent === null || section.maximum_utilization_percent === undefined
      ? "unknown" : `${section.maximum_utilization_percent}%`;
    byId(summaryId).textContent = `${section.available_samples || 0} available · ${section.unavailable_samples || 0} unknown · ${section.stale_samples || 0} stale · Average ${average} · Maximum ${maximum}. ${section.population || ""}`;
  }

  function renderTrend(containerId, valuesId, rows, valueKey, className) {
    const container = byId(containerId);
    const values = byId(valuesId);
    container.replaceChildren();
    values.replaceChildren();
    const validRows = rows.filter((row) => row.day || row.date);
    const maximum = Math.max(0, ...validRows.map((row) => Number(row[valueKey]) || 0));
    validRows.forEach((row) => {
      const day = row.day || row.date;
      const value = row[valueKey];
      const bar = document.createElement("div");
      bar.className = `trend-bar ${className}`;
      bar.style.height = `${maximum > 0 && typeof value === "number" ? Math.max(2, (value / maximum) * 120) : 0}px`;
      bar.title = `${day}: ${formatUsageValue(value)}`;
      container.appendChild(bar);
      const item = document.createElement("li");
      item.textContent = `${day}: ${formatUsageValue(value)}`;
      values.appendChild(item);
    });
    if (!validRows.length) {
      const item = document.createElement("li");
      item.textContent = "No daily samples for this filter.";
      values.appendChild(item);
    }
  }

  function renderTrends() {
    const dayRows = usageReport?.group_by === "day" ? usageReport.rows : [];
    renderTrend("fccTrend", "fccTrendValues", dayRows, "output_tokens", "fcc");
    renderTrend("rtkTrend", "rtkTrendValues", report?.optimizations.rtk.daily || [], "tokens_saved", "rtk");
  }

  function renderUsageRegions() {
    byId("usageLoading").hidden = !usageLoading;
    byId("usageError").hidden = !usageError;
    byId("usageError").textContent = usageError;
    byId("usageEmpty").hidden = usageLoading || !usageReport || usageReport.rows.length > 0;
    byId("usageTable").hidden = !usageReport || usageReport.rows.length === 0;
    byId("usageRefresh").disabled = usageLoading;
    if (usageReport) {
      byId("usageCoverage").textContent = `${usageReport.storage === "sqlite" ? "SQLite durable usage" : "In-memory usage (resets on restart)"} · Coverage ${usageReport.coverage_start} to ${usageReport.coverage_end} · Retention ${usageReport.retention_days} days · Generated ${usageReport.generated_at}`;
      renderUsageRows(usageReport.rows);
      renderContextSection("request_input", "requestContextRows", "requestContextSummary");
      renderContextSection("code_session_current", "codeContextRows", "codeContextSummary");
    }
    byId("usageExport").href = `/admin/api/usage/export?${usageQuery().toString()}`;
    renderTrends();
  }

  function renderUsage(payload) {
    usageReport = normalizeUsage(payload);
    usageError = "";
    renderUsageRegions();
    return usageReport;
  }

  function refreshUsage() {
    if (usageFlight) return usageFlight;
    if (typeof requestApi !== "function") return Promise.resolve(false);
    const request = ++usageRequest;
    const controller = new AbortController();
    usageController = controller;
    usageLoading = true;
    usageError = "";
    renderUsageRegions();
    usageFlight = (async () => {
      try {
        const payload = await requestApi(`/admin/api/usage?${usageQuery().toString()}`, { signal: controller.signal });
        if (request !== usageRequest) return false;
        renderUsage(payload);
        return true;
      } catch (error) {
        if (request !== usageRequest) return false;
        usageError = `Could not load FCC provider usage.${usageReport ? " Last valid usage remains visible." : ""}`;
        renderUsageRegions();
        return false;
      } finally {
        if (request === usageRequest) {
          usageLoading = false;
          usageFlight = null;
          usageController = null;
          renderUsageRegions();
        }
      }
    })();
    return usageFlight;
  }

  refreshButton.addEventListener("click", () => {
    void refresh();
    void refreshUsage();
  });
  byId("usageFilters").addEventListener("submit", (event) => {
    event.preventDefault();
    void refreshUsage();
  });

  window.fccTokenOptimization = { refresh, refreshUsage, setActive, renderExternal, renderUsage };
})();
