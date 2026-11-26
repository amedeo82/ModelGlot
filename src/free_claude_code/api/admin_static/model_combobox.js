(() => {
  class ModelGlotModelCombobox {
    static canonicalValue(input) {
      return input.dataset.canonicalValue ?? input.value;
    }

    constructor(
      input,
      {
        listboxId,
        label,
        values,
        emptyMessage,
        registry,
        displayValue = (value) => value,
        details = () => null,
        showSummary = false,
        onSelect = null,
        onClose = null,
      },
    ) {
      this.input = input;
      this.displayValue = displayValue;
      this.detailsFor = details;
      this.getValues = values;
      this.getEmptyMessage = emptyMessage;
      this.registry = registry;
      this.onSelect = onSelect;
      this.onClose = onClose;
      this.activeIndex = -1;
      this.query = "";
      this.customEdit = false;
      this.canonicalValue = String(input.value ?? "");
      input.dataset.canonicalValue = this.canonicalValue;
      input.modelCombobox = this;

      this.element = document.createElement("div");
      this.element.className = "model-combobox";
      this.listbox = document.createElement("div");
      this.listbox.className = "model-combobox-list";
      this.listbox.id = listboxId;
      this.listbox.setAttribute("role", "listbox");
      this.listbox.hidden = true;
      this.toggle = document.createElement("button");
      this.toggle.type = "button";
      this.toggle.className = "model-combobox-toggle";
      this.toggle.disabled = input.disabled;
      this.toggle.setAttribute("aria-label", `Show ${label} options`);

      input.setAttribute("role", "combobox");
      input.setAttribute("aria-autocomplete", "list");
      input.setAttribute("aria-haspopup", "listbox");
      for (const control of [input, this.toggle]) {
        control.setAttribute("aria-controls", this.listbox.id);
        control.setAttribute("aria-expanded", "false");
      }

      input.addEventListener("click", () => this.open());
      input.addEventListener("input", () => {
        this.canonicalValue = input.value;
        input.dataset.canonicalValue = this.canonicalValue;
        this.customEdit = true;
        this.updateSummary();
        this.open(input.value);
      });
      input.addEventListener("keydown", (event) => this.handleKeydown(event));
      this.toggle.addEventListener("mousedown", (event) => event.preventDefault());
      this.toggle.addEventListener("click", () => {
        if (this.isOpen) this.close();
        else this.open();
        input.focus();
      });
      this.listbox.addEventListener("mousedown", (event) => event.preventDefault());
      this.listbox.addEventListener("mousemove", (event) => {
        const optionEl = event.target.closest('[role="option"]');
        if (optionEl) this.setActive(this.visibleOptions.indexOf(optionEl));
      });
      this.listbox.addEventListener("click", (event) => {
        const optionEl = event.target.closest('[role="option"]');
        if (optionEl) this.select(optionEl.dataset.value);
      });

      this.element.append(input, this.toggle, this.listbox);
      this.container = this.element;
      this.summary = null;
      if (showSummary) {
        this.container = document.createElement("div");
        this.container.className = "model-picker-control";
        this.summary = document.createElement("div");
        this.summary.className = "model-picker-summary";
        this.summary.hidden = true;
        if (input.id) this.summary.id = `${input.id}-model-details`;
        this.container.append(this.element, this.summary);
      }
      this.updateSummary();
      registry.add(this);
    }

    get isOpen() {
      return this.element.classList.contains("open");
    }

    get visibleOptions() {
      return Array.from(this.listbox.querySelectorAll('[role="option"]'));
    }

    setCanonicalValue(value, { custom = false } = {}) {
      this.canonicalValue = String(value ?? "");
      this.input.dataset.canonicalValue = this.canonicalValue;
      this.customEdit = custom;
      this.input.value = custom ? this.canonicalValue : this.displayValue(this.canonicalValue);
      this.updateSummary();
    }

    refreshMetadata() {
      if (!this.customEdit) this.input.value = this.displayValue(this.canonicalValue);
      this.updateSummary();
      if (this.isOpen) this.render(this.customEdit ? this.query : this.input.value);
    }

    updateSummary() {
      if (!this.summary) return;
      const helper = window.ModelGlotModelPickerDetails;
      const visible = helper
        ? helper.renderSummary(
            this.summary,
            this.canonicalValue,
            this.customEdit ? this.canonicalValue : this.displayValue(this.canonicalValue),
            this.customEdit ? null : this.detailsFor(this.canonicalValue),
          )
        : false;
      this.summary.hidden = !visible;
      if (!this.summary.id) return;
      const ids = new Set(
        (this.input.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean),
      );
      if (visible) ids.add(this.summary.id);
      else ids.delete(this.summary.id);
      if (ids.size) this.input.setAttribute("aria-describedby", Array.from(ids).join(" "));
      else this.input.removeAttribute("aria-describedby");
    }

    open(query = this.input.value) {
      if (this.input.disabled) return;
      this.registry.forEach((combobox) => {
        if (combobox !== this && combobox.isOpen) combobox.close();
      });
      this.render(query);
      this.element.classList.add("open");
      this.listbox.hidden = false;
      this.setExpanded(true);
    }

    close() {
      if (!this.isOpen) return;
      this.element.classList.remove("open");
      this.listbox.hidden = true;
      this.activeIndex = -1;
      this.input.removeAttribute("aria-activedescendant");
      this.setExpanded(false);
      if (this.onClose) this.onClose();
    }

    setExpanded(expanded) {
      for (const control of [this.input, this.toggle]) {
        control.setAttribute("aria-expanded", String(expanded));
      }
    }

    render(query) {
      this.query = query;
      const normalizedQuery = query.trim().toLocaleLowerCase();
      const allValues = this.getValues();
      const helper = window.ModelGlotModelPickerDetails;
      const values = normalizedQuery
        ? allValues.filter((value) => {
            const searchText = helper
              ? helper.searchText(value, this.displayValue(value), this.detailsFor(value))
              : `${value} ${this.displayValue(value)}`;
            return searchText.toLocaleLowerCase().includes(normalizedQuery);
          })
        : allValues;
      this.listbox.replaceChildren();

      if (values.length === 0) {
        const empty = document.createElement("div");
        empty.className = "model-combobox-empty";
        empty.textContent = this.getEmptyMessage();
        this.listbox.appendChild(empty);
        this.activeIndex = -1;
        this.input.removeAttribute("aria-activedescendant");
        return;
      }

      values.forEach((value, index) => {
        const optionEl = document.createElement("div");
        optionEl.className = "model-combobox-option";
        optionEl.id = `${this.listbox.id}-option-${index}`;
        optionEl.dataset.value = value;
        optionEl.setAttribute("role", "option");
        const title = this.displayValue(value);
        optionEl.setAttribute(
          "aria-label",
          title === value ? title : `${title} — ${value}`,
        );
        if (helper) {
          optionEl.appendChild(helper.renderOption(value, title, this.detailsFor(value)));
        } else {
          optionEl.textContent = title;
        }
        this.listbox.appendChild(optionEl);
      });
      const selectedIndex = values.indexOf(ModelGlotModelCombobox.canonicalValue(this.input));
      this.setActive(selectedIndex >= 0 ? selectedIndex : 0, false);
    }

    setActive(index, scroll = true) {
      const options = this.visibleOptions;
      if (options.length === 0) return;
      this.activeIndex = Math.max(0, Math.min(index, options.length - 1));
      options.forEach((optionEl, optionIndex) => {
        const active = optionIndex === this.activeIndex;
        optionEl.classList.toggle("active", active);
        optionEl.setAttribute("aria-selected", String(active));
      });
      const activeOption = options[this.activeIndex];
      this.input.setAttribute("aria-activedescendant", activeOption.id);
      if (scroll) activeOption.scrollIntoView({ block: "nearest" });
    }

    move(offset) {
      const count = this.visibleOptions.length;
      if (count) this.setActive((this.activeIndex + offset + count) % count);
    }

    select(value) {
      this.setCanonicalValue(value);
      if (this.onSelect) this.onSelect(value);
      this.input.dispatchEvent(new Event("change", { bubbles: true }));
      this.close();
      this.input.focus();
    }

    handleKeydown(event) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (this.isOpen) {
          this.move(event.key === "ArrowDown" ? 1 : -1);
        } else {
          this.open();
          if (event.key === "ArrowUp") {
            this.setActive(this.visibleOptions.length - 1);
          }
        }
      } else if (this.isOpen && (event.key === "Home" || event.key === "End")) {
        event.preventDefault();
        this.setActive(event.key === "Home" ? 0 : this.visibleOptions.length - 1);
      } else if (this.isOpen && event.key === "Enter") {
        const active = this.visibleOptions[this.activeIndex];
        if (active) {
          event.preventDefault();
          this.select(active.dataset.value);
        }
      } else if (this.isOpen && event.key === "Escape") {
        event.preventDefault();
        this.close();
      } else if (this.isOpen && event.key === "Tab") {
        this.close();
      }
    }
  }

  window.ModelGlotModelCombobox = ModelGlotModelCombobox;
})();
