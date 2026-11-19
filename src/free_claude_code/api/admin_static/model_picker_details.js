(() => {
  function text(value) {
    return typeof value === "string" && value.trim() ? value.trim() : null;
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

  function viewModel(canonical, displayName, details = null) {
    const metadata = details && typeof details === "object" ? details : {};
    const title = text(displayName) || canonical;
    const providerLabel = text(metadata.provider_label);
    const description = text(metadata.description);
    const descriptionSource = description ? text(metadata.description_source) : null;
    const badges = [];
    if (metadata.supports_reasoning === true) {
      badges.push({ key: "reasoning", label: "Reasoning" });
    }
    if (Array.isArray(metadata.input_modalities) && metadata.input_modalities.includes("image")) {
      badges.push({ key: "image", label: "Image input" });
    }
    const context = positiveInteger(metadata.context_window_tokens);
    if (context !== null) {
      badges.push({ key: "context", label: `${formatTokens(context)} context` });
    }
    const output = positiveInteger(metadata.max_output_tokens);
    if (output !== null) {
      badges.push({ key: "output", label: `${formatTokens(output)} output` });
    }
    return { canonical, title, providerLabel, description, descriptionSource, badges };
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
      element.className = "model-picker-badge model-picker-badge--capability";
      element.dataset.capability = badge.key;
      element.textContent = badge.label;
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

  function appendCanonical(parent, view) {
    if (view.title === view.canonical) return;
    const canonical = document.createElement("code");
    canonical.className = "model-picker-canonical";
    canonical.textContent = view.canonical;
    parent.appendChild(canonical);
  }

  function renderOption(canonical, displayName, details = null) {
    const view = viewModel(canonical, displayName, details);
    const content = document.createElement("div");
    content.className = "model-picker-option-content";
    const heading = document.createElement("div");
    heading.className = "model-picker-heading";
    const title = document.createElement("span");
    title.className = "model-picker-title";
    title.textContent = view.title;
    heading.appendChild(title);
    content.appendChild(heading);
    appendBadges(content, view.badges, view.providerLabel);
    appendDescription(content, view);
    appendCanonical(content, view);
    return content;
  }

  function renderSummary(element, canonical, displayName, details = null) {
    const view = viewModel(canonical, displayName, details);
    const hasDetails =
      view.title !== view.canonical ||
      view.providerLabel ||
      view.description ||
      view.badges.length > 0;
    element.replaceChildren();
    element.hidden = !hasDetails;
    if (!hasDetails) return false;
    appendBadges(element, view.badges, view.providerLabel);
    appendDescription(element, view);
    appendCanonical(element, view);
    return true;
  }

  function searchText(canonical, displayName, details = null) {
    const metadata = details && typeof details === "object" ? details : {};
    return [canonical, displayName, metadata.provider_label, metadata.description]
      .filter((value) => typeof value === "string")
      .join(" ");
  }

  window.FccModelPickerDetails = {
    formatTokens,
    renderOption,
    renderSummary,
    searchText,
    viewModel,
  };
})();
