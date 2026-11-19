import pytest
from playwright.sync_api import Page, Route, expect

TOKEN_OPTIMIZATION_ENDPOINT = "**/admin/api/token-optimization"
TOKEN_OPTIMIZATION_PATH = "/admin/token_optimization"
GENERATED_AT = "2026-11-17T12:00:00.000Z"
UPDATED_AT = "2026-11-17T12:05:00.000Z"


def _rtk():
    return {
        "state": "available",
        "version": "0.44.2",
        "source": "rtk gain --format json",
        "basis": "tool_reported",
        "total_commands": 29,
        "tokens_before": 19_009,
        "tokens_after": 10_289,
        "tokens_saved": 8_720,
        "savings_percent": 45.87,
        "message": None,
    }


def _headroom():
    return {
        "state": "available",
        "version": "0.40.0",
        "source": "headroom savings --json",
        "basis": "tool_reported",
        "tokens_saved": 4_200,
        "tokens_before": 10_000,
        "calls": 12,
        "savings_percent": 42.0,
        "model_attribution": "unknown",
        "message": None,
    }


def _unavailable(tool, state, message):
    source = "rtk gain --format json" if tool == "rtk" else "headroom savings --json"
    counters = (
        ("total_commands", "tokens_before", "tokens_after", "tokens_saved")
        if tool == "rtk"
        else ("calls", "tokens_before", "tokens_saved")
    )
    return {
        "state": state,
        "version": None,
        "source": source,
        "basis": "tool_reported",
        "savings_percent": None,
        "message": message,
        **dict.fromkeys(counters),
    }


def _report(rtk=None, headroom=None, generated_at=GENERATED_AT):
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "optimizations": {
            "rtk": _rtk() if rtk is None else rtk,
            "headroom": _headroom() if headroom is None else headroom,
        },
        "notices": [],
    }


def _route_report(page: Page, payload):
    requests = []

    def respond(route: Route):
        requests.append(route.request)
        route.fulfill(json=payload)

    page.route(TOKEN_OPTIMIZATION_ENDPOINT, respond)
    return requests


def _card(page: Page, tool: str):
    return page.locator(f'[data-token-optimization-card="{tool}"]')


def _field(page: Page, tool: str, field: str):
    return _card(page, tool).locator(f'[data-field="{field}"]')


def _counter(page: Page, tool: str, counter: str):
    return _card(page, tool).locator(f'[data-counter="{counter}"]')


def _open_token_optimization(page: Page, admin_base_url: str):
    page.goto(f"{admin_base_url}{TOKEN_OPTIMIZATION_PATH}")
    expect(page.locator("#view-token_optimization")).to_be_visible()
    expect(page.locator("#tokenOptimizationRefresh")).to_be_enabled()


def test_navigation_direct_reload_history_and_apply_visibility(page, admin_base_url):
    requests = _route_report(page, _report())
    page.goto(f"{admin_base_url}/admin")
    expect(page.locator('[data-provider="nvidia_nim"]')).to_be_visible()
    expect(page.locator("#messageArea")).to_have_text("")
    assert requests == []

    page.get_by_role("button", name="Token optimization", exact=True).click()
    expect(page).to_have_url(f"{admin_base_url}{TOKEN_OPTIMIZATION_PATH}")
    expect(page.locator("#pageTitle")).to_have_text("Token optimization")
    expect(page.locator("#tokenOptimizationRtkState")).to_have_text("Available")
    expect(page.locator(".action-bar")).to_be_hidden()
    expect(page.locator("#applyButton")).to_be_hidden()
    expect(page.locator('.nav-link[data-view="token_optimization"]')).to_have_attribute(
        "aria-current", "page"
    )
    assert len(requests) == 1

    page.reload()
    expect(page.locator("#pageTitle")).to_have_text("Token optimization")
    expect(page.locator("#tokenOptimizationRtkState")).to_have_text("Available")
    expect(page.locator(".action-bar")).to_be_hidden()
    assert len(requests) == 2

    page.get_by_role("button", name="Providers", exact=True).click()
    expect(page.locator(".action-bar")).to_be_visible()
    assert len(requests) == 2
    page.go_back()
    expect(page).to_have_url(f"{admin_base_url}{TOKEN_OPTIMIZATION_PATH}")
    expect(page.locator("#tokenOptimizationRtkState")).to_have_text("Available")
    expect(page.locator(".action-bar")).to_be_hidden()
    assert len(requests) == 3
    page.go_forward()
    expect(page).to_have_url(f"{admin_base_url}/admin")
    expect(page.locator("#pageTitle")).to_have_text("Providers")
    assert len(requests) == 3

    _open_token_optimization(page, admin_base_url)
    expect(page.locator("#tokenOptimizationRtkState")).to_have_text("Available")
    assert len(requests) == 4
    page.wait_for_timeout(350)
    assert len(requests) == 4, "The read-only view must not poll its endpoint"


def test_populated_cards_provenance_and_private_fields_are_not_rendered(
    page, admin_base_url
):
    payload = _report()
    payload["optimizations"]["rtk"]["message"] = (
        '<img id="tokenOptimizationXss" src=x onerror="window.tokenXss = true">'
    )
    payload["optimizations"]["rtk"]["model_attribution"] = "must-not-render"
    payload["optimizations"]["headroom"]["path"] = (
        r"C:\Users\private\headroom-ledger.json"
    )
    payload["optimizations"]["headroom"]["cost_usd"] = 123.45
    _route_report(page, payload)
    _open_token_optimization(page, admin_base_url)

    expect(page.locator("#tokenOptimizationRtkState")).to_have_text("Available")
    expect(page.locator("#tokenOptimizationHeadroomState")).to_have_text("Available")
    for tool, version, source in (
        ("rtk", "0.44.2", "rtk gain --format json"),
        ("headroom", "0.40.0", "headroom savings --json"),
    ):
        expect(_field(page, tool, "version")).to_have_text(version)
        expect(_field(page, tool, "source")).to_have_text(source)
        expect(_field(page, tool, "basis")).to_have_text("tool_reported")

    expect(_counter(page, "rtk", "tokens_saved")).to_have_text("8,720")
    expect(_counter(page, "rtk", "total_commands")).to_have_text("29")
    expect(_counter(page, "rtk", "tokens_before")).to_have_text("19,009")
    expect(_counter(page, "rtk", "tokens_after")).to_have_text("10,289")
    expect(_counter(page, "rtk", "savings_percent")).to_have_text("45.87%")
    expect(_counter(page, "headroom", "tokens_saved")).to_have_text("4,200")
    expect(_counter(page, "headroom", "calls")).to_have_text("12")
    expect(_counter(page, "headroom", "tokens_before")).to_have_text("10,000")
    expect(_counter(page, "headroom", "savings_percent")).to_have_text("42%")
    expect(page.locator("#tokenOptimizationGeneratedAt")).to_have_text(GENERATED_AT)
    expect(page.locator("#tokenOptimizationError")).to_be_hidden()
    expect(page.locator("#tokenOptimizationEmpty")).to_be_hidden()

    methodology = page.locator(".token-optimization-methodology")
    expect(methodology).to_contain_text("separate, potentially overlapping ledgers")
    expect(methodology).to_contain_text("must not be added together")
    expect(page.locator("#tokenOptimizationXss")).to_have_count(0)
    assert page.evaluate("window.tokenXss === undefined")
    view_text = page.locator("#view-token_optimization").inner_text()
    assert "must-not-render" not in view_text
    assert "headroom-ledger.json" not in view_text
    assert "123.45" not in view_text
    assert "cost_usd" not in view_text
    assert "$" not in view_text
    expect(
        page.locator(
            "#view-token_optimization [data-combined-total], "
            "#view-token_optimization [data-usage], "
            "#view-token_optimization [data-trend], "
            "#view-token_optimization [data-cost]"
        )
    ).to_have_count(0)


def test_zero_headroom_is_available_and_does_not_imply_inactivity(page, admin_base_url):
    headroom = _headroom() | {
        "tokens_saved": 0,
        "tokens_before": 0,
        "calls": 0,
        "savings_percent": 0.0,
    }
    _route_report(page, _report(headroom=headroom))
    _open_token_optimization(page, admin_base_url)

    expect(page.locator("#tokenOptimizationHeadroomState")).to_have_text("Available")
    expect(_counter(page, "headroom", "tokens_saved")).to_have_text("0")
    expect(_counter(page, "headroom", "tokens_before")).to_have_text("0")
    expect(_counter(page, "headroom", "calls")).to_have_text("0")
    expect(_counter(page, "headroom", "savings_percent")).to_have_text("0%")
    expect(_field(page, "headroom", "message")).to_contain_text(
        "Zero counters do not prove inactivity"
    )
    expect(page.locator("#tokenOptimizationEmpty")).to_be_hidden()
    expect(_counter(page, "rtk", "tokens_saved")).to_have_text("8,720")


@pytest.mark.parametrize("unavailable_tool", ["rtk", "headroom"])
def test_one_unavailable_tool_keeps_the_other_report_visible(
    page, admin_base_url, unavailable_tool
):
    unavailable = _unavailable(
        unavailable_tool, "not_installed", f"{unavailable_tool} is missing"
    )
    payload = _report(
        rtk=unavailable if unavailable_tool == "rtk" else None,
        headroom=unavailable if unavailable_tool == "headroom" else None,
    )
    _route_report(page, payload)
    _open_token_optimization(page, admin_base_url)

    available_tool = "headroom" if unavailable_tool == "rtk" else "rtk"
    expect(_card(page, unavailable_tool)).to_have_attribute(
        "data-state", "not_installed"
    )
    expect(_field(page, unavailable_tool, "message")).to_have_text(
        f"{unavailable_tool} is missing"
    )
    expect(_counter(page, unavailable_tool, "tokens_saved")).to_have_text(
        "Not reported"
    )
    expect(_card(page, available_tool)).to_have_attribute("data-state", "available")
    expect(_counter(page, available_tool, "tokens_saved")).not_to_have_text(
        "Not reported"
    )
    expect(page.locator("#tokenOptimizationError")).to_be_hidden()
    expect(page.locator("#tokenOptimizationEmpty")).to_be_hidden()


def test_both_unavailable_timeout_and_invalid_output_states(page, admin_base_url):
    payload = _report(
        rtk=_unavailable("rtk", "timeout", "RTK collection timed out"),
        headroom=_unavailable(
            "headroom", "invalid_output", "Headroom output was invalid"
        ),
    )
    _route_report(page, payload)
    _open_token_optimization(page, admin_base_url)

    expect(page.locator("#tokenOptimizationRtkState")).to_have_text("Timed out")
    expect(page.locator("#tokenOptimizationHeadroomState")).to_have_text(
        "Invalid output"
    )
    expect(_field(page, "rtk", "message")).to_have_text("RTK collection timed out")
    expect(_field(page, "headroom", "message")).to_have_text(
        "Headroom output was invalid"
    )
    expect(page.locator("#tokenOptimizationEmpty")).to_be_visible()
    expect(page.locator("#tokenOptimizationEmpty")).to_contain_text(
        "do not prove tool inactivity"
    )
    expect(page.locator("#tokenOptimizationError")).to_be_hidden()
    expect(page.locator("#tokenOptimizationCards")).to_be_visible()


def test_malformed_response_has_error_and_empty_regions(page, admin_base_url):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    invalid = _headroom() | {"tokens_saved": -1}
    _route_report(page, _report(headroom=invalid))
    _open_token_optimization(page, admin_base_url)

    expect(page.locator("#tokenOptimizationError")).to_be_visible()
    expect(page.locator("#tokenOptimizationError")).to_contain_text(
        "invalid token optimization report"
    )
    expect(page.locator("#tokenOptimizationEmpty")).to_be_visible()
    expect(page.locator("#tokenOptimizationCards")).to_be_hidden()
    expect(page.locator("#tokenOptimizationGeneratedAt")).to_have_text("Not available")
    expect(page.locator("#tokenOptimizationRefresh")).to_be_enabled()
    assert errors == []


def test_loading_does_not_block_admin_and_concurrent_refreshes_coalesce(
    page, admin_base_url
):
    pending = []

    def hold(route: Route):
        pending.append(route)
        page.evaluate(
            "window.heldTokenOptimization = (window.heldTokenOptimization || 0) + 1"
        )

    page.route(TOKEN_OPTIMIZATION_ENDPOINT, hold)
    page.goto(f"{admin_base_url}{TOKEN_OPTIMIZATION_PATH}")
    page.wait_for_function("window.heldTokenOptimization === 1")
    expect(page.locator("#tokenOptimizationLoading")).to_be_visible()
    expect(page.locator("#tokenOptimizationCards")).to_be_hidden()
    expect(page.locator("#tokenOptimizationEmpty")).to_be_hidden()
    expect(page.locator("#tokenOptimizationRefresh")).to_be_disabled()
    expect(page.locator("#tokenOptimizationRefresh")).to_have_attribute(
        "aria-busy", "true"
    )

    same_flight = page.evaluate(
        """() => {
          const first = window.fccTokenOptimization.refresh();
          const second = window.fccTokenOptimization.refresh();
          return first === second;
        }"""
    )
    assert same_flight
    assert len(pending) == 1

    page.get_by_role("button", name="Providers", exact=True).click()
    expect(page.locator('[data-provider="nvidia_nim"]')).to_be_visible()
    expect(page.locator(".action-bar")).to_be_visible()
    assert len(pending) == 1
    pending.pop().fulfill(json=_report())
    expect(page.locator("#tokenOptimizationRoot")).to_have_attribute(
        "aria-busy", "false"
    )
    page.unroute(TOKEN_OPTIMIZATION_ENDPOINT, hold)
    _route_report(page, _report())
    page.go_back()
    expect(page.locator("#tokenOptimizationRtkState")).to_have_text("Available")
    expect(page.locator("#tokenOptimizationLoading")).to_be_hidden()
    expect(page.locator("#tokenOptimizationRefresh")).to_be_enabled()


def test_stale_response_from_previous_activation_is_ignored(page, admin_base_url):
    pending = []

    def hold(route: Route):
        pending.append(route)
        page.evaluate(
            "window.heldStaleTokenOptimization = "
            "(window.heldStaleTokenOptimization || 0) + 1"
        )

    page.route(TOKEN_OPTIMIZATION_ENDPOINT, hold)
    page.goto(f"{admin_base_url}{TOKEN_OPTIMIZATION_PATH}")
    page.wait_for_function("window.heldStaleTokenOptimization === 1")
    page.get_by_role("button", name="Providers", exact=True).click()
    page.get_by_role("button", name="Token optimization", exact=True).click()
    page.wait_for_function("window.heldStaleTokenOptimization === 2")
    assert len(pending) == 2

    stale, current = pending
    refreshed = _report(generated_at=UPDATED_AT)
    refreshed["optimizations"]["rtk"]["tokens_saved"] = 9_000
    current.fulfill(json=refreshed)
    expect(_counter(page, "rtk", "tokens_saved")).to_have_text("9,000")
    expect(page.locator("#tokenOptimizationGeneratedAt")).to_have_text(UPDATED_AT)

    stale.fulfill(json=_report())
    page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )
    expect(_counter(page, "rtk", "tokens_saved")).to_have_text("9,000")
    expect(page.locator("#tokenOptimizationGeneratedAt")).to_have_text(UPDATED_AT)
    expect(page.locator("#tokenOptimizationError")).to_be_hidden()
    assert len(pending) == 2


def test_manual_refresh_preserves_last_valid_report_on_errors(page, admin_base_url):
    current = {"status": 200, "payload": _report()}
    requests = []

    def respond(route: Route):
        requests.append(route.request)
        route.fulfill(status=current["status"], json=current["payload"])

    page.route(TOKEN_OPTIMIZATION_ENDPOINT, respond)
    _open_token_optimization(page, admin_base_url)
    expect(_counter(page, "rtk", "tokens_saved")).to_have_text("8,720")

    current["payload"] = _report(generated_at=UPDATED_AT)
    current["payload"]["optimizations"]["rtk"]["tokens_saved"] = 9_000
    page.locator("#tokenOptimizationRefresh").click()
    expect(_counter(page, "rtk", "tokens_saved")).to_have_text("9,000")
    expect(page.locator("#tokenOptimizationGeneratedAt")).to_have_text(UPDATED_AT)
    assert len(requests) == 2

    current.update(status=503, payload={"detail": "Collector timed out safely"})
    page.locator("#tokenOptimizationRefresh").click()
    expect(page.locator("#tokenOptimizationError")).to_contain_text(
        "Collector timed out safely"
    )
    expect(page.locator("#tokenOptimizationError")).to_contain_text(
        "Last valid data is still shown"
    )
    expect(_counter(page, "rtk", "tokens_saved")).to_have_text("9,000")
    expect(page.locator("#tokenOptimizationGeneratedAt")).to_have_text(UPDATED_AT)
    expect(page.locator("#tokenOptimizationRefresh")).to_be_enabled()
    assert len(requests) == 3

    current.update(status=200, payload=_report(headroom={"state": "invalid"}))
    page.locator("#tokenOptimizationRefresh").click()
    expect(page.locator("#tokenOptimizationError")).to_contain_text(
        "invalid token optimization report"
    )
    expect(_counter(page, "rtk", "tokens_saved")).to_have_text("9,000")
    expect(_counter(page, "headroom", "tokens_saved")).to_have_text("4,200")
    expect(page.locator("#tokenOptimizationGeneratedAt")).to_have_text(UPDATED_AT)
    assert len(requests) == 4

    current["payload"] = _report()
    page.locator("#tokenOptimizationRefresh").click()
    expect(page.locator("#tokenOptimizationError")).to_be_hidden()
    expect(_counter(page, "rtk", "tokens_saved")).to_have_text("8,720")
    assert len(requests) == 5


@pytest.mark.parametrize("width", [1280, 768, 390])
def test_token_optimization_layout_is_responsive(page, admin_base_url, width):
    page.set_viewport_size({"width": width, "height": 900})
    _route_report(page, _report())
    _open_token_optimization(page, admin_base_url)
    expect(page.locator("#tokenOptimizationRtkState")).to_have_text("Available")

    rtk_box = _card(page, "rtk").bounding_box()
    headroom_box = _card(page, "headroom").bounding_box()
    if width <= 900:
        assert headroom_box["y"] >= rtk_box["y"] + rtk_box["height"] - 1
    else:
        assert headroom_box["y"] == pytest.approx(rtk_box["y"], abs=1)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(page.locator("#tokenOptimizationRefresh")).to_be_visible()
    expect(page.locator(".token-optimization-methodology")).to_be_visible()
    expect(page.locator(".action-bar")).to_be_hidden()


def _usage_payload():
    return {
        "schema_version": 1,
        "generated_at": GENERATED_AT,
        "coverage_start": "2026-11-01T00:00:00.000Z",
        "coverage_end": GENERATED_AT,
        "retention_days": 30,
        "storage": "sqlite",
        "group_by": "day",
        "rows": [
            {
                "day": "2026-11-17",
                "provider_id": None,
                "gateway_model": None,
                "provider_model": None,
                "request_count": 3,
                "successful_count": 2,
                "failed_count": 1,
                "cancelled_count": 0,
                "physical_attempt_count": 4,
                "input_total_tokens": 100,
                "output_tokens": 40,
                "cache_read_tokens": 0,
                "estimated_input_tokens": 110,
            }
        ],
        "context": {
            "request_input": {
                "rows": [
                    {
                        "kind": "request_input",
                        "provider_id": "provider",
                        "provider_model": "model",
                        "context_used_tokens": 25,
                        "context_window_tokens": 100,
                        "utilization_percent": 25.0,
                        "sampled_at": GENERATED_AT,
                    }
                ],
                "available_samples": 1,
                "unavailable_samples": 0,
                "stale_samples": 0,
                "average_utilization_percent": 25.0,
                "maximum_utilization_percent": 25.0,
                "population": "successful provider-reported request inputs",
            },
            "code_session_current": {
                "rows": [
                    {
                        "kind": "code_session_current",
                        "provider_id": "provider",
                        "provider_model": "model",
                        "context_used_tokens": 50,
                        "context_window_tokens": 100,
                        "utilization_percent": 50.0,
                        "sampled_at": GENERATED_AT,
                        "stale": False,
                    }
                ],
                "available_samples": 1,
                "unavailable_samples": 0,
                "stale_samples": 0,
                "average_utilization_percent": 50.0,
                "maximum_utilization_percent": 50.0,
                "population": "current Code session context snapshots",
            },
        },
        "notices": [],
    }


def test_usage_context_trends_filters_and_csv_download(page, admin_base_url):
    rtk = _rtk()
    rtk["daily"] = [
        {
            "date": "2026-11-17",
            "tokens_saved": 60,
            "tokens_before": 100,
            "tokens_after": 40,
            "savings_percent": 60.0,
            "basis": "tool_reported",
        }
    ]
    _route_report(page, _report(rtk=rtk))
    usage_requests = []

    def usage_response(route):
        usage_requests.append(route.request.url)
        route.fulfill(json=_usage_payload())

    page.route("**/admin/api/usage?**", usage_response)
    page.route(
        "**/admin/api/usage/export?**",
        lambda route: route.fulfill(
            body="day,output_tokens\r\n2026-11-17,40\r\n",
            content_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="fcc-usage.csv"'},
        ),
    )
    _open_token_optimization(page, admin_base_url)

    expect(page.locator("#usageRows tr")).to_have_count(1)
    expect(page.locator("#usageRows")).to_contain_text("40")
    expect(page.locator("#requestContextRows")).to_contain_text("25%")
    expect(page.locator("#codeContextRows")).to_contain_text("50%")
    expect(page.locator("#requestContextSummary")).to_contain_text("Average 25%")
    expect(page.locator("#codeContextSummary")).to_contain_text("Average 50%")
    expect(page.locator("#fccTrendValues")).to_contain_text("2026-11-17: 40")
    expect(page.locator("#rtkTrendValues")).to_contain_text("2026-11-17: 60")
    expect(page.locator("#usageCoverage")).to_contain_text("SQLite durable usage")
    expect(page.locator("#usageCoverage")).to_contain_text("Retention 30 days")

    page.locator("#usageGroupBy").select_option("provider")
    page.locator("#usageRefresh").click()
    expect(page.locator("#usageExport")).to_have_attribute(
        "href", "/admin/api/usage/export?group_by=provider"
    )
    assert any("group_by=provider" in url for url in usage_requests)

    with page.expect_download() as download_info:
        page.locator("#usageExport").click()
    assert download_info.value.suggested_filename == "fcc-usage.csv"


def test_usage_failure_does_not_hide_external_or_previous_usage(page, admin_base_url):
    _route_report(page, _report())
    current = {"calls": 0}

    def usage_response(route):
        current["calls"] += 1
        if current["calls"] == 1:
            route.fulfill(json=_usage_payload())
        else:
            route.fulfill(status=500, json={"detail": "Usage report is unavailable."})

    page.route("**/admin/api/usage?**", usage_response)
    _open_token_optimization(page, admin_base_url)
    expect(page.locator("#usageRows tr")).to_have_count(1)
    page.locator("#usageRefresh").click()
    expect(page.locator("#usageError")).to_contain_text(
        "Last valid usage remains visible"
    )
    expect(page.locator("#usageRows tr")).to_have_count(1)
    expect(page.locator("#tokenOptimizationRtkState")).to_have_text("Available")
