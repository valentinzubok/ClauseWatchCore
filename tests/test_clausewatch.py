import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import load_contract  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
mod = load_contract(ROOT)
gl = sys.modules["genlayer"]

OWNER = "0x1111111111111111111111111111111111111111"
OTHER = "0x2222222222222222222222222222222222222222"
URL = "https://example.com/terms"

V1 = "Pro plan costs 20 USD per month. Cancel any time. Updated 2026-01-01."
V1_COSMETIC = "Pro plan costs 20 USD per month. Cancel any time. Updated 2026-02-09."
V2_MATERIAL = (
    "Pro plan costs 30 USD per month. Cancel with 30 days notice. Updated 2026-02-09."
)


def _watch(**pages):
    gl.pages = {URL: V1, **pages}
    gl.verdict = '{"material": true}'
    gl.message.sender_address = OWNER
    c = mod.ClauseWatch(OWNER)
    c.register_watch("vendor/terms", URL, "Vendor terms", "")
    return c


def test_register_freezes_baseline():
    c = _watch()
    w = json.loads(c.get_watch("vendor/terms"))
    assert w["baseline_version"] == 1
    assert len(w["baseline_hash"]) == 64
    assert w["status"] == "active"
    assert w["criteria"] == mod.DEFAULT_CRITERIA
    assert json.loads(c.list_ids()) == ["vendor/terms"]
    # The full text is kept on chain but not returned by get_watch.
    assert "baseline_text" not in w
    assert json.loads(c.get_baseline_text("vendor/terms"))["baseline_text"] == V1


def test_register_rejects_bad_input():
    gl.pages = {URL: V1}
    c = mod.ClauseWatch(OWNER)
    with pytest.raises(Exception, match="https"):
        c.register_watch("w1", "http://example.com", "label", "")
    with pytest.raises(Exception, match="label"):
        c.register_watch("w1", URL, "", "")
    c.register_watch("w1", URL, "label", "")
    with pytest.raises(Exception, match="already exists"):
        c.register_watch("w1", URL, "label", "")
    with pytest.raises(Exception, match="fetch failed"):
        c.register_watch("w2", "https://example.com/missing", "label", "")


def test_unchanged_check_raises_no_alert():
    c = _watch()
    c.check("vendor/terms")
    w = json.loads(c.get_watch("vendor/terms"))
    assert w["last_result"] == "unchanged"
    assert w["checks"] == 1 and w["changes"] == 0
    assert json.loads(c.list_alerts("")) == []


def test_cosmetic_change_is_reported_but_not_material():
    c = _watch()
    gl.pages[URL] = V1_COSMETIC
    gl.verdict = '{"material": false}'
    c.check("vendor/terms")
    w = json.loads(c.get_watch("vendor/terms"))
    assert w["last_result"] == "cosmetic_change"
    assert w["changes"] == 1 and w["material_changes"] == 0
    alert = json.loads(c.list_alerts("vendor/terms"))[0]
    assert alert["material"] is False
    assert alert["previous_hash"] != alert["current_hash"]


def test_material_change_and_acknowledge_moves_baseline():
    c = _watch()
    gl.pages[URL] = V2_MATERIAL
    gl.verdict = '{"material": true}'
    c.check("vendor/terms")
    w = json.loads(c.get_watch("vendor/terms"))
    assert w["last_result"] == "material_change"
    assert w["material_changes"] == 1
    assert w["pending_hash"] and w["baseline_version"] == 1

    c.acknowledge("vendor/terms")
    w = json.loads(c.get_watch("vendor/terms"))
    assert w["baseline_version"] == 2
    assert w["pending_hash"] == ""
    assert (
        json.loads(c.get_baseline_text("vendor/terms"))["baseline_text"] == V2_MATERIAL
    )

    # The new baseline is the reference now: checking again finds no change.
    c.check("vendor/terms")
    assert json.loads(c.get_watch("vendor/terms"))["last_result"] == "unchanged"


def test_non_boolean_verdict_fails_safe_to_material():
    c = _watch()
    gl.pages[URL] = V2_MATERIAL
    for bad in [
        '{"material": "yes"}',
        '{"material": null}',
        "not json",
        '["material"]',
    ]:
        gl.verdict = bad
        c.check("vendor/terms")
        assert (
            json.loads(c.get_watch("vendor/terms"))["last_result"] == "material_change"
        )


def test_acknowledge_and_status_are_guarded():
    c = _watch()
    with pytest.raises(Exception, match="nothing to acknowledge"):
        c.acknowledge("vendor/terms")

    gl.pages[URL] = V2_MATERIAL
    c.check("vendor/terms")
    gl.message.sender_address = OTHER
    with pytest.raises(Exception, match="only the watch creator"):
        c.acknowledge("vendor/terms")
    with pytest.raises(Exception, match="only the watch creator"):
        c.set_status("vendor/terms", "paused")

    gl.message.sender_address = OWNER
    c.set_status("vendor/terms", "paused")
    with pytest.raises(Exception, match="paused"):
        c.check("vendor/terms")
    with pytest.raises(Exception, match="active or paused"):
        c.set_status("vendor/terms", "sleeping")
    c.set_status("vendor/terms", "active")
    c.check("vendor/terms")


def test_unknown_ids_and_stats():
    c = _watch()
    assert json.loads(c.get_watch("nope"))["error"] == "unknown watch_id"
    assert json.loads(c.get_alert("alert-99"))["error"] == "unknown alert_id"
    with pytest.raises(Exception, match="unknown watch_id"):
        c.check("nope")

    gl.pages[URL] = V2_MATERIAL
    c.check("vendor/terms")
    stats = json.loads(c.get_stats())
    assert stats == {
        "watches": 1,
        "active": 1,
        "checks": 1,
        "alerts": 1,
        "material_alerts": 1,
        "cosmetic_alerts": 0,
    }
    assert c.get_owner() == OWNER.lower()


def test_alerts_are_trimmed_and_ordered():
    c = _watch()
    for i in range(mod.MAX_ALERTS + 5):
        gl.pages[URL] = f"{V2_MATERIAL} build {i}"
        c.check("vendor/terms")
    rows = json.loads(c.list_alerts(""))
    assert len(rows) == mod.MAX_ALERTS
    ids = [int(r["alert_id"].split("-")[-1]) for r in rows]
    assert ids == sorted(ids, reverse=True)


def test_long_text_is_bounded():
    gl.pages = {URL: "x " * (mod.MAX_TEXT * 2)}
    gl.message.sender_address = OWNER
    c = mod.ClauseWatch(OWNER)
    c.register_watch("big", URL, "Big page", "")
    text = json.loads(c.get_baseline_text("big"))["baseline_text"]
    assert len(text) == mod.MAX_TEXT
