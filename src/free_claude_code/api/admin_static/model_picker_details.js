(() => {
  const CATALOG_SOURCE = "models.dev";

  function text(value, maximum = 512) {
    return typeof value === "string" && value.trim()
      ? value.trim().slice(0, maximum)
      : null;
  }

  function positiveInteger(value) {
    return Number.isInteger(value) && value > 0 ? value : null;
  }

  function formatTokens(value) {
    const units = ["", "K", "M", "B"];
    let scaled = value;
    let unit = 0;
    while (scaled >= 1024 && unit < units.length - 1) {
      scaled /= 1024;
      unit += 1;
    }
    const rounded = scaled >= 100 ? Math.round(scaled) : Math.round(scaled * 10) / 10;
    return `${rounded}${units[unit]}`;
  }

  function formatExactTokens(value) {
    return `${value.toLocaleString("en-US")} tokens`;
  }

  function catalogDetails(details) {
    return details.catalog && typeof details.catalog === "object" ? details.catalog : null;
  }

  function viewModel(canonical, displayName, details = null) {
    const metadata = details && typeof details === "object" ? details : {};
    const catalog = catalogDetails(metadata);
    const title = text(displayName) || canonical;
    const providerLabel = text(metadata.provider_label);
    const description = text(metadata.description, 4096);
    const descriptionSource = description ? text(metadata.description_source) : null;
    const badges = [];
    const stats = [];
    const addBadge = (key, label, authority = "runtime") => {
      if (!badges.some((badge) => badge.key === key)) {
        badges.push({ key, label, authority });
      }
    };
    const addLimit = (key, label, runtimeValue, catalogValue) => {
      const runtime = positiveInteger(runtimeValue);
      const declared = positiveInteger(catalogValue);
      const value = runtime ?? declared;
      if (value === null) return;
      const authority = runtime !== null ? "runtime" : "catalog";
      addBadge(key, `${formatTokens(value)} ${label}`, authority);
      stats.push({ key, label, value, authority });
    };

    if (metadata.supports_reasoning === true) addBadge("reasoning", "Reasoning");
    if (
      catalog?.reasoning === true &&
      metadata.supports_reasoning !== true &&
      metadata.supports_reasoning !== false
    ) {
      addBadge("reasoning", "Reasoning", "catalog");
    }
    if (catalog?.tool_call === true) addBadge("tools", "Tool calling", "catalog");
    if (catalog?.structured_output === true) {
      addBadge("structured-output", "Structured output", "catalog");
    }

    const runtimeModalities = Array.isArray(metadata.input_modalities)
      ? metadata.input_modalities
      : null;
    if (runtimeModalities?.includes("image")) addBadge("image", "Image input");
    const catalogInput = Array.isArray(catalog?.modalities?.input)
      ? catalog.modalities.input
      : null;
    if (catalogInput?.includes("image") && runtimeModalities === null) {
      addBadge("image", "Image input", "catalog");
    }
    for (const [modality, label] of [
      ["audio", "Audio input"],
      ["video", "Video input"],
      ["pdf", "PDF input"],
    ]) {
      if (catalogInput?.includes(modality)) addBadge(modality, label, "catalog");
    }
    if (catalog?.open_weights === true) {
      addBadge("open-weights", "Open weights", "neutral");
    }
    const lifecycle = text(catalog?.status, 64);
    if (lifecycle) addBadge("lifecycle", lifecycle, "neutral");

    addLimit(
      "context",
      "context",
      metadata.context_window_tokens,
      catalog?.limit?.context,
    );
    addLimit("output", "output", metadata.max_output_tokens, catalog?.limit?.output);

    const lab = catalog?.lab && typeof catalog.lab === "object" ? catalog.lab : null;
    const fetchedAt = Number.isFinite(catalog?.fetched_at) ? catalog.fetched_at : null;
    return {
      canonical,
      title,
      providerLabel,
      description,
      descriptionSource,
      badges,
      stats,
      labLabel: text(lab?.label, 256),
      providerLogoUrl: safeAssetUrl(catalog?.provider_logo_url),
      labLogoUrl: safeAssetUrl(lab?.logo_url),
      sourceProviderId: text(catalog?.source_provider_id, 128),
      canonicalModelId: text(catalog?.canonical_model_id, 256),
      fetchedAt,
      lastUpdated: text(catalog?.last_updated, 64),
      releaseDate: text(catalog?.release_date, 64),
      stale: catalog?.stale === true,
      hasCatalog: catalog !== null,
    };
  }

  function safeAssetUrl(value) {
    return (
      typeof value === "string" &&
      value.startsWith("/") &&
      !value.startsWith("//") &&
      !/[\\\u0000-\u001f]/.test(value)
        ? value
        : null
    );
  }

  function initials(label) {
    const words = (label || "?").split(/\s+/).filter(Boolean);
    if (words.length > 1) return words.slice(0, 2).map((word) => word[0]).join("").toUpperCase();
    return (words[0] || "?").slice(0, 2).toUpperCase();
  }

  function appendLogo(parent, url, label, kind) {
    const container = document.createElement("span");
    container.className = `model-picker-logo model-picker-logo--${kind}`;
    const fallback = () => {
      const element = document.createElement("span");
      element.className = "model-picker-logo-fallback";
      element.setAttribute("aria-hidden", "true");
      element.textContent = initials(label);
      container.replaceChildren(element);
    };
    if (!url) {
      fallback();
    } else {
      const image = document.createElement("img");
      image.src = url;
      image.alt = "";
      image.setAttribute("aria-hidden", "true");
      image.addEventListener("error", fallback, { once: true });
      container.appendChild(image);
    }
    parent.appendChild(container);
  }

  function appendIdentity(parent, view, selected = false) {
    const identity = document.createElement("div");
    identity.className = "model-picker-identity";
    const logos = document.createElement("div");
    logos.className = "model-picker-logos";
    appendLogo(logos, view.providerLogoUrl, view.providerLabel || "Provider", "provider");
    if (selected && view.labLabel) {
      appendLogo(logos, view.labLogoUrl, view.labLabel, "lab");
    }
    const heading = document.createElement("div");
    heading.className = "model-picker-heading";
    const title = document.createElement("span");
    title.className = "model-picker-title";
    title.textContent = view.title;
    heading.appendChild(title);
    const identityText = document.createElement("div");
    identityText.className = "model-picker-attribution";
    identityText.textContent = view.labLabel
      ? `${view.labLabel} · Hosted by ${view.providerLabel || view.sourceProviderId || "unknown provider"}`
      : view.providerLabel || "Custom model";
    heading.appendChild(identityText);
    identity.append(logos, heading);
    parent.appendChild(identity);
  }

  function createBadgeIcon(key) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("model-picker-badge-icon");
    svg.dataset.icon = key;
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const shapes = {
      reasoning: [
        ["path", { d: "M8 2a3 3 0 0 0-3 3v1a3 3 0 0 0-1 5 3 3 0 0 0 4 3 3 3 0 0 0 4-3 3 3 0 0 0-1-5V5a3 3 0 0 0-3-3Zm0 0v12" }],
      ],
      tools: [["path", { d: "M10 2a4 4 0 0 0-5 5l-3 3a1.4 1.4 0 0 0 2 2l3-3a4 4 0 0 0 5-5L9 7 7 5l3-3Z" }]],
      "structured-output": [["path", { d: "M6 2H4v4L2 8l2 2v4h2m4-12h2v4l2 2-2 2v4h-2" }]],
      image: [
        ["rect", { x: 2, y: 3, width: 12, height: 10, rx: 1 }],
        ["circle", { cx: 5, cy: 6, r: 1 }],
        ["path", { d: "m3 12 3-3 2 2 2-2 3 3" }],
      ],
      audio: [
        ["path", { d: "M3 6h3l4-3v10l-4-3H3Zm9-1a4 4 0 0 1 0 6m-1-4a2 2 0 0 1 0 2" }],
      ],
      video: [
        ["rect", { x: 2, y: 3, width: 8, height: 10, rx: 1 }],
        ["path", { d: "m10 6 4-2v8l-4-2Z" }],
      ],
      pdf: [["path", { d: "M4 2h5l3 3v9H4Zm5 0v3h3M6 9h4m-4 2h4" }]],
      "open-weights": [["path", { d: "M3 7h10v7H3Zm2 0V5a3 3 0 0 1 6 0M8 10v2" }]],
      context: [
        ["ellipse", { cx: 8, cy: 4, rx: 5, ry: 2 }],
        ["path", { d: "M3 4v4c0 1 2 2 5 2s5-1 5-2V4m-10 4v4c0 1 2 2 5 2s5-1 5-2V8" }],
      ],
      output: [["path", { d: "M3 8h9M9 4l4 4-4 4m4-4v6" }]],
      lifecycle: [
        ["circle", { cx: 8, cy: 8, r: 6 }],
        ["path", { d: "M8 7v4m0-6v1" }],
      ],
      release: [
        ["rect", { x: 3, y: 3, width: 10, height: 10, rx: 1 }],
        ["path", { d: "M5 2v3m6-3v3M5 8h6m-6 2h4" }],
      ],
    };
    for (const [tag, attributes] of shapes[key] || shapes.lifecycle) {
      const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
      for (const [name, value] of Object.entries(attributes)) {
        element.setAttribute(name, String(value));
      }
      svg.appendChild(element);
    }
    return svg;
  }

  function appendBadges(parent, badges, providerLabel = null) {
    if (!providerLabel && badges.length === 0) return;
    const container = document.createElement("div");
    container.className = "model-picker-badges";
    if (providerLabel) {
      const provider = document.createElement("span");
      provider.className = "model-picker-badge model-picker-badge--provider";
      provider.textContent = providerLabel;
      container.appendChild(provider);
    }
    for (const badge of badges) {
      const element = document.createElement("span");
      element.className = `model-picker-badge model-picker-badge--capability model-picker-badge--${badge.authority}`;
      element.dataset.capability = badge.key;
      element.dataset.authority = badge.authority;
      const icon = createBadgeIcon(badge.key);
      const label = document.createElement("span");
      label.textContent = badge.label;
      element.append(icon, label);
      if (badge.authority === "catalog") {
        const provenance = document.createElement("span");
        provenance.className = "model-picker-badge-source";
        provenance.textContent = "Catalog";
        element.appendChild(provenance);
        element.title = `${badge.label}: models.dev catalog declaration, not an FCC runtime guarantee.`;
        element.setAttribute("aria-label", `${badge.label}, models.dev catalog declaration`);
      } else if (badge.authority === "runtime") {
        element.title = `${badge.label}: provider/FCC-confirmed runtime fact.`;
      } else {
        element.title = `${badge.label}: neutral catalog information, not a runtime capability.`;
      }
      container.appendChild(element);
    }
    parent.appendChild(container);
  }

  function appendDescription(parent, view) {
    if (!view.description) return;
    const description = document.createElement("div");
    description.className = "model-picker-description";
    const content = document.createElement("span");
    content.textContent = view.description;
    description.appendChild(content);
    if (view.descriptionSource) {
      const separator = document.createElement("span");
      separator.className = "model-picker-source-separator";
      separator.setAttribute("aria-hidden", "true");
      separator.textContent = " · ";
      const source = document.createElement("span");
      source.className = "model-picker-source";
      source.textContent = view.descriptionSource;
      description.append(separator, source);
    }
    parent.appendChild(description);
  }

  function appendStats(parent, view) {
    if (view.stats.length === 0 && !view.releaseDate) return;
    const stats = document.createElement("dl");
    stats.className = "model-picker-stats";
    for (const stat of view.stats) {
      const item = document.createElement("div");
      item.className = `model-picker-stat model-picker-stat--${stat.authority}`;
      item.dataset.stat = stat.key;
      const term = document.createElement("dt");
      term.append(
        createBadgeIcon(stat.key),
        document.createTextNode(stat.label === "context" ? "Context" : "Max output"),
      );
      const value = document.createElement("dd");
      value.textContent = formatExactTokens(stat.value);
      const source = document.createElement("span");
      source.className = "model-picker-stat-source";
      source.textContent = stat.authority === "runtime" ? "Provider/FCC" : "models.dev catalog";
      value.appendChild(document.createElement("br"));
      value.appendChild(source);
      item.append(term, value);
      stats.appendChild(item);
    }
    if (view.releaseDate) {
      const item = document.createElement("div");
      item.className = "model-picker-stat model-picker-stat--neutral";
      item.dataset.stat = "release";
      const term = document.createElement("dt");
      term.append(createBadgeIcon("release"), document.createTextNode("Released"));
      const value = document.createElement("dd");
      value.textContent = view.releaseDate;
      item.append(term, value);
      stats.appendChild(item);
    }
    parent.appendChild(stats);
  }

  function appendCatalogSource(parent, view) {
    if (!view.hasCatalog) return;
    const source = document.createElement("div");
    source.className = "model-picker-catalog-source";
    const parts = [
      `Source: ${CATALOG_SOURCE}`,
      view.sourceProviderId ? `Provider scope: ${view.sourceProviderId}` : null,
      view.lastUpdated ? `Catalog updated: ${view.lastUpdated}` : null,
      view.stale ? "Stale cache" : "Fresh cache",
    ].filter(Boolean);
    source.textContent = parts.join(" · ");
    const explanation = document.createElement("div");
    explanation.className = "model-picker-catalog-explanation";
    explanation.textContent =
      "Dashed Catalog badges are models.dev declarations, not FCC runtime guarantees. Provider/FCC facts take precedence.";
    parent.append(source, explanation);
  }

  function renderOption(canonical, displayName, details = null) {
    const view = viewModel(canonical, displayName, details);
    const content = document.createElement("div");
    content.className = "model-picker-option-content";
    appendIdentity(content, view);
    appendBadges(content, view.badges, view.providerLabel);
    appendDescription(content, view);
    return content;
  }

  function renderSummary(element, canonical, displayName, details = null) {
    const view = viewModel(canonical, displayName, details);
    const hasDetails =
      view.title !== view.canonical ||
      view.providerLabel ||
      view.description ||
      view.badges.length > 0 ||
      view.hasCatalog;
    element.replaceChildren();
    element.hidden = !hasDetails;
    if (!hasDetails) return false;
    element.classList.add("model-picker-summary--selected");
    appendIdentity(element, view, true);
    appendBadges(element, view.badges, view.providerLabel);
    appendDescription(element, view);
    appendStats(element, view);
    appendCatalogSource(element, view);
    return true;
  }

  function searchText(canonical, displayName, details = null) {
    const view = viewModel(canonical, displayName, details);
    return [
      canonical,
      displayName,
      view.providerLabel,
      view.description,
      view.labLabel,
      view.sourceProviderId,
      view.canonicalModelId,
      ...view.badges.map((badge) => `${badge.label} ${badge.authority}`),
    ]
      .filter((value) => typeof value === "string")
      .join(" ");
  }

  window.FccModelPickerDetails = {
    formatExactTokens,
    formatTokens,
    renderOption,
    renderSummary,
    searchText,
    viewModel,
  };
})();
