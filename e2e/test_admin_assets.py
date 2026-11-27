"""Rendered contracts for Admin asset generation consistency."""

from typing import TypedDict
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Error, Page, Request, expect

from e2e.form_support import assert_autofill_opt_out
from e2e.layout import visible_bounds
from e2e.provider_support import api_key_input, open_provider
from modelglot.core.version import package_version


class _Measurements(TypedDict):
    top: float
    bottom: float
    bar: float
    endGap: float | None
    headingGap: float


class _ModelPickerResult(TypedDict):
    knownBadges: list[str]
    unknownBadges: list[str]
    disabledBadges: list[str]
    optionText: str
    optionImages: int
    optionBadges: int
    optionCanonical: int
    customVisible: bool
    customChildren: int


class _CatalogDetailsResult(TypedDict):
    badges: list[list[str]]
    conflictBadges: list[list[str]]
    exact: str
    summaryText: str
    summaryHtml: str
    catalogBadges: int
    runtimeBadges: int
    fallbacks: int
    images: int
    errorFallback: str
    errorImages: int
    context: str
    output: str
    release: str


@pytest.mark.parametrize("width", [1280, 900, 390])
def test_admin_page_spacing_matches_visible_action_bar(
    page: Page, admin_base_url: str, width: int
):
    page.set_viewport_size({"width": width, "height": 720})
    page.goto(f"{admin_base_url}/admin")
    expect(page.locator("#messageArea")).to_have_text("")

    def assert_spacing():
        page.wait_for_function("""() => !document.querySelector('.action-bar')
          .getAnimations({subtree: true}).some(animation => animation.playState === 'running')""")
        # Wait for layout/ResizeObserver delivery, then inspect rendered geometry.
        page.evaluate(
            "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
        )
        measurements: _Measurements = page.evaluate("""() => {
          const main = document.querySelector('.main');
          const style = getComputedStyle(main);
          const bar = document.querySelector('.action-bar');
          const sections = [...document.querySelectorAll('.admin-view:not([hidden]) .form-sections > *')];
          const last = sections.filter((section) => !section.hidden).at(-1);
          const heading = document.querySelector('#pageTitle');
          const range = document.createRange();
          range.selectNodeContents(heading);
          const text = range.getBoundingClientRect();
          const context = document.createElement('canvas').getContext('2d');
          context.font = getComputedStyle(heading).font;
          const metrics = context.measureText(heading.textContent);
          const inkTop = text.top + (text.height - metrics.fontBoundingBoxAscent - metrics.fontBoundingBoxDescent) / 2
            + metrics.fontBoundingBoxAscent - metrics.actualBoundingBoxAscent;
          return {
            top: parseFloat(style.paddingTop),
            bottom: parseFloat(style.paddingBottom),
            bar: bar.getBoundingClientRect().height,
            endGap: last ? main.getBoundingClientRect().bottom - last.getBoundingClientRect().bottom : null,
            headingGap: inkTop - main.getBoundingClientRect().top,
          };
        }""")
        assert measurements["bottom"] - measurements["bar"] == pytest.approx(
            measurements["top"], abs=1
        )
        # Ink can overshoot the font's cap metric; allow pixel rounding as well.
        assert measurements["headingGap"] == pytest.approx(measurements["top"], abs=2)
        if measurements["endGap"] is not None:
            assert measurements["endGap"] - measurements["bar"] >= (
                measurements["top"] - 1
            )

    for title in ("Providers", "Model Config", "Messaging"):
        page.get_by_role("button", name=title, exact=True).click()
        expect(page.locator("#pageTitle")).to_have_text(title)
        assert_spacing()

    original_height = visible_bounds(page.locator(".action-bar"))["height"]
    page.locator("#messageArea").evaluate(
        "node => node.textContent = 'A longer validation message that wraps onto multiple lines. '.repeat(20)"
    )
    assert_spacing()
    assert visible_bounds(page.locator(".action-bar"))["height"] > original_height
    page.set_viewport_size({"width": 700 if width > 900 else 1200, "height": 720})
    assert_spacing()

    page.get_by_role("button", name="Integrations", exact=True).click()
    expect(page.locator(".action-bar")).to_be_hidden()
    assert_spacing()
    page.get_by_role("button", name="Providers", exact=True).click()
    expect(page.locator(".action-bar")).to_be_visible()
    assert_spacing()


def test_messaging_settings_follow_selected_platform(
    page: Page, admin_base_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MESSAGING_PLATFORM", raising=False)
    page.goto(f"{admin_base_url}/admin/messaging")
    page.get_by_role("button", name="Messaging", exact=True).click()

    platform = page.locator("#field-MESSAGING_PLATFORM")
    messaging = page.locator("#section-messaging")
    telegram = page.locator("#section-telegram")
    discord = page.locator("#section-discord")
    workspace = page.locator("#section-workspace")
    voice = page.locator("#section-voice")

    expect(platform).to_have_value("discord")
    expect(platform).to_be_enabled()
    expect(messaging).to_be_visible()
    expect(telegram).to_be_hidden()
    expect(discord).to_be_visible()
    expect(workspace).to_be_visible()
    expect(voice).to_be_visible()

    platform.select_option("telegram")
    expect(telegram).to_be_visible()
    expect(discord).to_be_hidden()
    expect(workspace).to_be_visible()
    expect(voice).to_be_visible()
    expect(page.locator("#field-TELEGRAM_BOT_TOKEN")).to_be_visible()

    platform.select_option("discord")
    expect(telegram).to_be_hidden()
    expect(discord).to_be_visible()
    expect(workspace).to_be_visible()
    expect(voice).to_be_visible()
    expect(page.locator("#field-DISCORD_BOT_TOKEN")).to_be_visible()

    platform.select_option("none")
    expect(telegram).to_be_hidden()
    expect(discord).to_be_hidden()
    expect(workspace).to_be_hidden()
    expect(voice).to_be_hidden()
    expect(page.locator("#dirtyState")).to_have_text("1 unsaved change")


def test_settings_text_fields_opt_out_of_autofill(
    page: Page, admin_base_url: str
) -> None:
    page.goto(f"{admin_base_url}/admin")
    expect(page.locator("#messageArea")).to_have_text("")
    for title in ("Providers", "Model Config", "Messaging", "Integrations"):
        page.get_by_role("button", name=title, exact=True).click()
        assert_autofill_opt_out(page)
    page.get_by_role("button", name="Providers", exact=True).click()
    open_provider(page, "nvidia_nim")
    assert_autofill_opt_out(page)
    key = api_key_input(page, "NVIDIA_NIM_API_KEY")
    expect(key).to_have_value("")
    expect(key).to_have_attribute("type", "password")
    expect(key).to_have_attribute("autocapitalize", "none")
    expect(key).to_have_attribute("spellcheck", "false")
    expect(key).to_have_attribute("autocorrect", "off")
    expect(page.locator('.field input[type="password"]')).to_have_count(1)
    key.fill("manually-entered-api-key")
    expect(key).to_have_value("manually-entered-api-key")
    expect(page.locator("#saveProvider")).to_be_enabled()


def test_selected_admin_tab_survives_refresh_and_browser_navigation(
    page: Page, admin_base_url: str
):
    page.goto(f"{admin_base_url}/admin")
    for title, path in (
        ("Model Config", "/admin/model_config"),
        ("Messaging", "/admin/messaging"),
        ("Integrations", "/admin/integrations"),
        ("Providers", "/admin"),
    ):
        page.get_by_role("button", name=title, exact=True).click()
        expect(page).to_have_url(f"{admin_base_url}{path}")
        page.reload()
        expect(page.locator("#pageTitle")).to_have_text(title)
        expect(page.get_by_role("button", name=title, exact=True)).to_have_attribute(
            "aria-current", "page"
        )
    page.go_back()
    expect(page.locator("#pageTitle")).to_have_text("Integrations")
    page.go_forward()
    expect(page.locator("#pageTitle")).to_have_text("Providers")


def test_admin_removes_chat_drafts_and_preserves_other_storage(
    page: Page, admin_base_url: str
):
    page.add_init_script("""(() => {
      for (let index = 0; index < 16; index++) {
        sessionStorage.setItem(`modelglot.chat.draft.${index}`, `old draft ${index}`);
      }
      for (let index = 0; index < 16; index++) {
        sessionStorage.setItem(`modelglot.code.${index}`, `keep code draft ${index}`);
      }
      sessionStorage.setItem('modelglot.chat.draftWithoutDot', 'keep unrelated key');
      sessionStorage.setItem('other-admin-state', 'keep admin state');
    })();""")
    page.goto(f"{admin_base_url}/admin")
    expect(page.locator('[data-provider="nvidia_nim"]')).to_be_visible()
    assert page.evaluate("Object.fromEntries(Object.entries(sessionStorage))") == {
        **{
            f"modelglot.code.{index}": f"keep code draft {index}" for index in range(16)
        },
        "modelglot.chat.draftWithoutDot": "keep unrelated key",
        "other-admin-state": "keep admin state",
    }
    expect(page.locator('.nav-link[data-view="providers"]')).to_have_attribute(
        "aria-current", "page"
    )
    expect(page.get_by_role("button", name="Chat Sessions", exact=True)).to_have_count(
        0
    )
    page.get_by_role("button", name="Code sessions", exact=True).click()
    expect(page).to_have_url(f"{admin_base_url}/admin/code")
    expect(
        page.get_by_role("button", name="New code session", exact=True)
    ).to_be_enabled()


def test_admin_storage_denial_keeps_admin_usable(page: Page, admin_base_url: str):
    errors = []
    warnings = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: (
            warnings.append(message.text) if message.type == "warning" else None
        ),
    )
    page.add_init_script("""Object.defineProperty(window, 'sessionStorage', {
      get() { throw new DOMException('Storage is denied', 'SecurityError'); }
    });""")
    page.goto(f"{admin_base_url}/admin")
    expect(page.locator('[data-provider="nvidia_nim"]')).to_be_visible()
    page.get_by_role("button", name="Code sessions", exact=True).click()
    expect(
        page.get_by_role("button", name="New code session", exact=True)
    ).to_be_enabled()
    assert errors == []
    assert any("Chat draft cleanup deferred" in message for message in warnings)


def test_admin_loads_current_release_assets_before_rendering_dynamic_content(
    page: Page,
    admin_base_url: str,
) -> None:
    requested_paths: list[str] = []
    page_errors: list[str] = []

    def record_request(request: Request) -> None:
        requested_paths.append(urlsplit(request.url).path)

    def record_page_error(error: Error) -> None:
        page_errors.append(str(error))

    page.on("request", record_request)
    page.on("pageerror", record_page_error)
    page.goto(f"{admin_base_url}/admin")

    expect(page.locator('[data-provider="nvidia_nim"]')).to_be_visible()
    expect(page.locator(".brand p")).to_have_text(
        f"Server Control · v{package_version()}"
    )
    logo_link = page.get_by_role("link", name="Open ModelGlot on GitHub")
    expect(logo_link).to_be_visible()
    expect(logo_link).to_have_attribute("href", "https://github.com/amedeo82/ModelGlot")
    expect(logo_link).to_have_attribute("target", "_blank")
    expect(page.locator('link[rel="icon"]')).to_have_attribute(
        "href", f"/admin/assets/{package_version()}/app-icon.svg"
    )

    versioned_root = f"/admin/assets/{package_version()}"
    assert f"{versioned_root}/app-icon.svg" in requested_paths
    assert f"{versioned_root}/admin.css" in requested_paths
    assert f"{versioned_root}/code_sessions.css" in requested_paths
    assert f"{versioned_root}/model_picker_details.js" in requested_paths
    assert f"{versioned_root}/model_combobox.js" in requested_paths
    assert f"{versioned_root}/form_controls.js" in requested_paths
    assert f"{versioned_root}/code_sessions.js" in requested_paths
    assert f"{versioned_root}/admin.js" in requested_paths
    assert "/admin/assets/admin.css" not in requested_paths
    assert "/admin/assets/code_sessions.css" not in requested_paths
    assert "/admin/assets/model_picker_details.js" not in requested_paths
    assert "/admin/assets/model_combobox.js" not in requested_paths
    assert "/admin/assets/code_sessions.js" not in requested_paths
    assert "/admin/assets/admin.js" not in requested_paths
    assert not any("/chat_sessions." in path for path in requested_paths)
    assert page_errors == []


def test_model_picker_details_enforce_authority_and_safe_text_rendering(
    page: Page, admin_base_url: str
) -> None:
    page.goto(f"{admin_base_url}/admin")
    expect(page.locator('[data-provider="nvidia_nim"]')).to_be_visible()

    result: _ModelPickerResult = page.evaluate("""() => {
      const helper = window.ModelGlotModelPickerDetails;
      const known = helper.viewModel('open_router/known', 'Known', {
        supports_reasoning: true,
        input_modalities: ['text', 'image', 'video'],
        context_window_tokens: 262144,
        max_output_tokens: 32768,
      });
      const unknown = helper.viewModel('nvidia_nim/minimax', 'MiniMax', {
        description: '1M context',
        supports_reasoning: null,
        input_modalities: null,
        context_window_tokens: null,
        max_output_tokens: null,
      });
      const disabled = helper.viewModel('open_router/disabled', 'Disabled', {
        supports_reasoning: false,
        input_modalities: [],
        context_window_tokens: 0,
        max_output_tokens: -1,
      });
      const description = '<img src=x onerror=alert(1)> 1M context';
      const option = helper.renderOption('custom/model', 'Custom <b>title</b>', {
        description,
        description_source: 'models.dev',
        supports_reasoning: false,
        input_modalities: ['video'],
      });
      document.body.appendChild(option);
      const summary = document.createElement('div');
      const customVisible = helper.renderSummary(summary, 'custom/model', 'custom/model');
      return {
        knownBadges: known.badges.map(badge => badge.label),
        unknownBadges: unknown.badges,
        disabledBadges: disabled.badges,
        optionText: option.textContent,
        optionImages: option.querySelectorAll('img, b').length,
        optionBadges: option.querySelectorAll('.model-picker-badge--capability').length,
        optionCanonical: option.querySelectorAll('.model-picker-canonical').length,
        customVisible,
        customChildren: summary.childElementCount,
      };
    }""")

    assert result["knownBadges"] == [
        "Reasoning",
        "Image input",
        "256K context",
        "32K output",
    ]
    assert result["unknownBadges"] == []
    assert result["disabledBadges"] == []
    assert "<img src=x onerror=alert(1)> 1M context" in result["optionText"]
    assert "Custom <b>title</b>" in result["optionText"]
    assert result["optionImages"] == 0
    assert result["optionBadges"] == 0
    assert result["optionCanonical"] == 0
    assert result["customVisible"] is False
    assert result["customChildren"] == 0


def test_model_picker_catalog_details_keep_provenance_conflicts_and_fallbacks(
    page: Page, admin_base_url: str
) -> None:
    page.goto(f"{admin_base_url}/admin")
    expect(page.locator('[data-provider="nvidia_nim"]')).to_be_visible()

    result: _CatalogDetailsResult = page.evaluate("""() => {
      const helper = window.ModelGlotModelPickerDetails;
      const catalog = {
        source: 'models.dev', source_provider_id: 'nvidia',
        canonical_model_id: 'minimax/MiniMax-M3.1-Flash',
        lab: {id: 'minimax', label: 'MiniMax <b>Lab</b>', logo_url: null},
        provider_logo_url: null, fetched_at: 1763654400, stale: true,
        last_updated: '2026-11-01', reasoning: true, tool_call: true,
        structured_output: true,
        modalities: {input: ['text', 'image', 'video'], output: ['text']},
        limit: {context: 262144, input: 262144, output: 262144},
        release_date: '2026-10-19', status: null, open_weights: true,
      };
      const details = {
        provider_label: 'NVIDIA NIM', description: '1M context',
        description_source: 'models.dev', supports_reasoning: null,
        input_modalities: null, context_window_tokens: null,
        max_output_tokens: null, catalog,
      };
      const minimax = helper.viewModel(
        'nvidia_nim/minimaxai/minimax-m3.1-flash', 'MiniMax-M3.1-Flash', details,
      );
      const conflict = helper.viewModel('nvidia_nim/model', 'Model', {
        ...details, supports_reasoning: false, context_window_tokens: 131072,
      });
      const summary = document.createElement('div');
      helper.renderSummary(
        summary, 'nvidia_nim/minimaxai/minimax-m3.1-flash', 'MiniMax-M3.1-Flash', details,
      );
      document.body.appendChild(summary);
      const brokenLogo = document.createElement('div');
      helper.renderSummary(brokenLogo, 'nvidia_nim/model', 'Model', {
        ...details,
        catalog: {...catalog, provider_logo_url: '/admin/assets/missing/providers/nope.svg'},
      });
      brokenLogo.querySelector('img').dispatchEvent(new Event('error'));
      return {
        badges: minimax.badges.map(badge => [badge.key, badge.authority]),
        conflictBadges: conflict.badges.map(badge => [badge.key, badge.label, badge.authority]),
        exact: helper.formatExactTokens(262144),
        summaryText: summary.textContent,
        summaryHtml: summary.innerHTML,
        catalogBadges: summary.querySelectorAll('.model-picker-badge--catalog').length,
        runtimeBadges: summary.querySelectorAll('.model-picker-badge--runtime').length,
        fallbacks: summary.querySelectorAll('.model-picker-logo-fallback').length,
        images: summary.querySelectorAll('img').length,
        errorFallback: brokenLogo.querySelector('.model-picker-logo-fallback').textContent,
        errorImages: brokenLogo.querySelectorAll('img').length,
        context: summary.querySelector('[data-stat="context"]').textContent,
        output: summary.querySelector('[data-stat="output"]').textContent,
        release: summary.querySelector('[data-stat="release"]').textContent,
      };
    }""")

    assert ["reasoning", "catalog"] in result["badges"]
    assert ["tools", "catalog"] in result["badges"]
    assert ["structured-output", "catalog"] in result["badges"]
    assert ["video", "catalog"] in result["badges"]
    assert ["context", "catalog"] in result["badges"]
    assert ["reasoning", "catalog"] not in result["conflictBadges"]
    assert ["context", "128K context", "runtime"] in result["conflictBadges"]
    assert result["exact"] == "262,144 tokens"
    assert result["context"] == "Context262,144 tokensmodels.dev catalog"
    assert result["output"] == "Max output262,144 tokensmodels.dev catalog"
    assert result["release"] == "Released2026-10-19"
    assert "Source: models.dev" in result["summaryText"]
    assert "Provider scope: nvidia" in result["summaryText"]
    assert "Stale cache" in result["summaryText"]
    assert "not ModelGlot runtime guarantees" in result["summaryText"]
    assert "MiniMax <b>Lab</b>" in result["summaryText"]
    assert "<b>Lab</b>" not in result["summaryHtml"]
    assert result["catalogBadges"] >= 7
    assert result["runtimeBadges"] == 0
    assert result["fallbacks"] == 2
    assert result["images"] == 0
    assert result["errorFallback"] == "NN"
    assert result["errorImages"] == 0
