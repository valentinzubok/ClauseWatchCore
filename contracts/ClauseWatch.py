# v0.3.0
# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }

import genlayer as gl
import hashlib
import json
import re

# ClauseWatch — consensus monitoring of terms, pricing and policy pages.
# Copyright (c) 2026 Valentyn Zubok. MIT License.
# Runtime: GenVM v0.3.0-rc7 — Studio Dev / Studio Next (chain 61997).
#
# Why: vendors change prices, SLAs and terms quietly. A hash alone is useless
# (every cache-buster or timestamp changes it) and a plain LLM check is not
# reproducible. ClauseWatch splits the problem in two consensus steps:
#
#   register_watch → validators fetch the page and agree on its SHA-256 and text
#                    (eq_principle.strict_eq). That frozen text is the baseline.
#   check          → validators fetch it again under strict_eq.
#                      same hash      → "unchanged", no alert, cheap and deterministic.
#                      hash differs   → validators' LLMs compare BASELINE vs CURRENT text
#                                       against the watch criteria and agree on one boolean
#                                       `material` (prompt_comparative). Cosmetic churn
#                                       (dates, counters, whitespace) is not material.
#   acknowledge    → the watch owner accepts the current text as the new baseline (v+1),
#                    so the next check compares against what was actually reviewed.
#
# Fail-safe: if the model output is not a literal boolean, `material` becomes True.
# For a monitor, a false alert is cheap and a missed change is not.

MAX_ID_LEN = 64
MAX_LABEL_LEN = 120
MAX_CRITERIA_LEN = 600
MAX_URL_LEN = 300
MAX_TEXT = 6000
PREVIEW_CHARS = 280
MAX_ALERTS = 200
MAX_WATCHES = 200
HASH_ALGO = "sha256"

STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"

DEFAULT_CRITERIA = (
    "Material: price or fee changes, payment or billing terms, liability limits, "
    "data sharing or privacy scope, termination or renewal rules, SLA numbers. "
    "Not material: dates, counters, ids, tracking parameters, formatting, typos, "
    "navigation or marketing copy."
)

ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
HTTPS_RE = re.compile(r"^https://[^\s<>\"']+$", re.IGNORECASE)
WS_RE = re.compile(r"\s+")


def _normalize_id(value: str, label: str = "watch_id") -> str:
    v = str(value or "").strip().lower()
    if not v or len(v) > MAX_ID_LEN:
        raise Exception(f"{label} required (max {MAX_ID_LEN} chars)")
    for ch in v:
        if not (("a" <= ch <= "z") or ("0" <= ch <= "9") or ch in "-_./"):
            raise Exception(f"{label}: use a-z 0-9 - _ . / only")
    return v


def _require_address(label: str, value: str) -> str:
    v = str(value or "").strip()
    if not ADDR_RE.match(v):
        raise Exception(f"{label} must be a 0x address")
    return v.lower()


def _require_https(url: str) -> str:
    u = str(url or "").strip()
    if len(u) > MAX_URL_LEN or not HTTPS_RE.match(u):
        raise Exception(f"url must be https and at most {MAX_URL_LEN} chars")
    return u


def _text(label: str, value: str, max_len: int) -> str:
    v = str(value or "").strip()
    if not v:
        raise Exception(f"{label} required")
    if len(v) > max_len:
        raise Exception(f"{label} too long (max {max_len})")
    return v


def _normalize(text: str) -> str:
    return WS_RE.sub(" ", str(text or "")).strip()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _capture(url: str) -> str:
    """Fetch a page and return a deterministic snapshot. Runs inside strict_eq."""
    entry = {
        "url": url,
        "content_hash": "",
        "text": "",
        "preview": "",
        "status": "error",
    }
    try:
        raw = gl.nondet.web.render(url, mode="text")
        if raw is None or str(raw).strip() == "":
            raw = gl.nondet.web.render(url, mode="html")
        normalized = _normalize(raw if raw is not None else "")
        if normalized == "":
            entry["status"] = "empty"
        else:
            bounded = normalized[:MAX_TEXT]
            entry["content_hash"] = _hash_text(bounded)
            entry["text"] = bounded
            entry["preview"] = bounded[:PREVIEW_CHARS]
            entry["status"] = "ok"
    except Exception as exc:
        entry["preview"] = str(exc)[:120]
    return json.dumps(entry, sort_keys=True, separators=(",", ":"))


def _freeze(url: str) -> dict:
    def leader_fn() -> str:
        return _capture(url)

    snap = json.loads(gl.eq_principle.strict_eq(leader_fn))
    if snap.get("status") != "ok":
        raise Exception("page fetch failed or empty — nothing to freeze")
    return snap


def _literal_bool(value) -> bool:
    """Only a literal JSON boolean counts; anything else fails safe to True (alert)."""
    return value if isinstance(value, bool) else True


def _judge_change(criteria: str, label: str, baseline: str, current: str) -> str:
    prompt = (
        "You compare two versions of the same web page for a change monitor.\n"
        'Answer ONLY with JSON: {"material": true} or {"material": false}.\n'
        "material = true when the CURRENT version changes the substance described by CRITERIA.\n"
        "material = false when the difference is only cosmetic: dates, counters, ids, tracking "
        "parameters, ordering, whitespace, typos or unrelated marketing copy.\n\n"
        f"WATCH: {label}\n\nCRITERIA:\n{criteria}\n\n"
        f"BASELINE VERSION:\n{baseline}\n\nCURRENT VERSION:\n{current}\n"
    )
    try:
        out = gl.nondet.exec_prompt(prompt, response_format="json")
    except Exception:
        try:
            out = gl.nondet.exec_prompt(prompt)
        except Exception:
            return json.dumps({"material": True}, sort_keys=True, separators=(",", ":"))

    if isinstance(out, str):
        try:
            out = json.loads(out)
        except Exception:
            return json.dumps({"material": True}, sort_keys=True, separators=(",", ":"))
    if not isinstance(out, dict):
        return json.dumps({"material": True}, sort_keys=True, separators=(",", ":"))
    return json.dumps(
        {"material": _literal_bool(out.get("material"))},
        sort_keys=True,
        separators=(",", ":"),
    )


class ClauseWatch(gl.contract.Contract):
    owner: str
    watches_json: str
    alerts_json: str
    order_json: str
    alert_seq: str

    def __init__(self, owner_address: str):
        self.owner = _require_address("owner_address", owner_address)
        self.watches_json = "{}"
        self.alerts_json = "{}"
        self.order_json = "[]"
        self.alert_seq = "0"

    # ── storage helpers ────────────────────────────────────────────────────

    def _load(self, field: str):
        return json.loads(getattr(self, field))

    def _save(self, field: str, value) -> None:
        setattr(self, field, json.dumps(value, sort_keys=True, separators=(",", ":")))

    def _require_watch(self, wid: str, watches: dict) -> dict:
        if wid not in watches:
            raise Exception("unknown watch_id")
        return watches[wid]

    def _require_watch_owner(self, watch: dict) -> str:
        caller = str(gl.message.sender_address).lower()
        if caller != watch["created_by"] and caller != self.owner:
            raise Exception("only the watch creator or the contract owner may do this")
        return caller

    def _next_alert_id(self) -> str:
        n = int(self.alert_seq or "0") + 1
        self.alert_seq = str(n)
        return f"alert-{n}"

    def _trim_alerts(self, alerts: dict) -> dict:
        """Keep the newest MAX_ALERTS entries (called after inserting the new one)."""
        if len(alerts) <= MAX_ALERTS:
            return alerts
        keys = sorted(alerts.keys(), key=lambda k: int(k.split("-")[-1]))
        for k in keys[: len(alerts) - MAX_ALERTS]:
            del alerts[k]
        return alerts

    # ── writes ─────────────────────────────────────────────────────────────

    @gl.public.write
    def register_watch(
        self, watch_id: str, url: str, label: str, criteria: str
    ) -> None:
        """Freeze the current page as the baseline of a new watch."""
        wid = _normalize_id(watch_id)
        watches = self._load("watches_json")
        if wid in watches:
            raise Exception("watch_id already exists")
        if len(watches) >= MAX_WATCHES:
            raise Exception("watch limit reached")

        target = _require_https(url)
        title = _text("label", label, MAX_LABEL_LEN)
        rules = str(criteria or "").strip() or DEFAULT_CRITERIA
        if len(rules) > MAX_CRITERIA_LEN:
            raise Exception(f"criteria too long (max {MAX_CRITERIA_LEN})")

        snap = _freeze(target)
        creator = str(gl.message.sender_address).lower()
        watches[wid] = {
            "watch_id": wid,
            "url": target,
            "label": title,
            "criteria": rules,
            "created_by": creator,
            "status": STATUS_ACTIVE,
            "baseline_hash": snap["content_hash"],
            "baseline_text": snap["text"],
            "baseline_preview": snap["preview"],
            "baseline_version": 1,
            "pending_hash": "",
            "pending_text": "",
            "pending_preview": "",
            "checks": 0,
            "changes": 0,
            "material_changes": 0,
            "last_result": "baseline",
            "last_alert_id": "",
        }
        self._save("watches_json", watches)
        order = self._load("order_json")
        order.append(wid)
        self._save("order_json", order)

    @gl.public.write
    def check(self, watch_id: str) -> None:
        """Re-fetch under consensus; if the text changed, judge whether it is material."""
        wid = _normalize_id(watch_id)
        watches = self._load("watches_json")
        watch = self._require_watch(wid, watches)
        if watch.get("status") != STATUS_ACTIVE:
            raise Exception("watch is paused")

        snap = _freeze(watch["url"])
        watch["checks"] = int(watch.get("checks", 0)) + 1

        if snap["content_hash"] == watch["baseline_hash"]:
            watch["last_result"] = "unchanged"
            watch["pending_hash"] = ""
            watch["pending_text"] = ""
            watch["pending_preview"] = ""
            watches[wid] = watch
            self._save("watches_json", watches)
            return

        def leader_fn() -> str:
            return _judge_change(
                watch["criteria"], watch["label"], watch["baseline_text"], snap["text"]
            )

        try:
            verdict_json = gl.eq_principle.prompt_comparative(
                leader_fn,
                principle="The boolean field `material` must be identical.",
            )
        except Exception:
            verdict_json = gl.eq_principle.strict_eq(leader_fn)

        try:
            verdict = (
                json.loads(verdict_json)
                if isinstance(verdict_json, str)
                else verdict_json
            )
        except Exception:
            verdict = {"material": True}
        material = _literal_bool(
            verdict.get("material") if isinstance(verdict, dict) else None
        )

        alert_id = self._next_alert_id()
        alerts = self._load("alerts_json")
        alerts[alert_id] = {
            "alert_id": alert_id,
            "watch_id": wid,
            "label": watch["label"],
            "url": watch["url"],
            "previous_hash": watch["baseline_hash"],
            "current_hash": snap["content_hash"],
            "baseline_version": int(watch.get("baseline_version", 1)),
            "material": material,
            "preview": snap["preview"],
            "raised_by": str(gl.message.sender_address).lower(),
        }
        self._save("alerts_json", self._trim_alerts(alerts))

        watch["changes"] = int(watch.get("changes", 0)) + 1
        if material:
            watch["material_changes"] = int(watch.get("material_changes", 0)) + 1
        watch["last_result"] = "material_change" if material else "cosmetic_change"
        watch["last_alert_id"] = alert_id
        watch["pending_hash"] = snap["content_hash"]
        watch["pending_text"] = snap["text"]
        watch["pending_preview"] = snap["preview"]
        watches[wid] = watch
        self._save("watches_json", watches)

    @gl.public.write
    def acknowledge(self, watch_id: str) -> None:
        """Accept the last checked version as the new baseline (watch creator or owner)."""
        wid = _normalize_id(watch_id)
        watches = self._load("watches_json")
        watch = self._require_watch(wid, watches)
        self._require_watch_owner(watch)
        if not watch.get("pending_hash"):
            raise Exception("nothing to acknowledge")

        watch["baseline_hash"] = watch["pending_hash"]
        watch["baseline_text"] = watch["pending_text"]
        watch["baseline_preview"] = watch["pending_preview"]
        watch["baseline_version"] = int(watch.get("baseline_version", 1)) + 1
        watch["pending_hash"] = ""
        watch["pending_text"] = ""
        watch["pending_preview"] = ""
        watch["last_result"] = "acknowledged"
        watches[wid] = watch
        self._save("watches_json", watches)

    @gl.public.write
    def set_status(self, watch_id: str, status: str) -> None:
        """Pause or resume a watch (watch creator or contract owner)."""
        wid = _normalize_id(watch_id)
        want = str(status or "").strip().lower()
        if want not in (STATUS_ACTIVE, STATUS_PAUSED):
            raise Exception("status must be active or paused")
        watches = self._load("watches_json")
        watch = self._require_watch(wid, watches)
        self._require_watch_owner(watch)
        watch["status"] = want
        watches[wid] = watch
        self._save("watches_json", watches)

    @gl.public.write
    def transfer_ownership(self, new_owner: str) -> None:
        if str(gl.message.sender_address).lower() != self.owner:
            raise Exception("only owner")
        self.owner = _require_address("new_owner", new_owner)

    # ── views ──────────────────────────────────────────────────────────────

    @gl.public.view
    def get_watch(self, watch_id: str) -> str:
        wid = _normalize_id(watch_id)
        watches = self._load("watches_json")
        if wid not in watches:
            return json.dumps({"error": "unknown watch_id"})
        watch = dict(watches[wid])
        # Full texts stay on chain but are large; views return previews.
        watch.pop("baseline_text", None)
        watch.pop("pending_text", None)
        return json.dumps(watch, sort_keys=True, separators=(",", ":"))

    @gl.public.view
    def get_baseline_text(self, watch_id: str) -> str:
        wid = _normalize_id(watch_id)
        watches = self._load("watches_json")
        if wid not in watches:
            return json.dumps({"error": "unknown watch_id"})
        return json.dumps(
            {
                "watch_id": wid,
                "baseline_version": watches[wid].get("baseline_version", 1),
                "baseline_hash": watches[wid].get("baseline_hash", ""),
                "baseline_text": watches[wid].get("baseline_text", ""),
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @gl.public.view
    def list_ids(self) -> str:
        return self.order_json

    @gl.public.view
    def get_alert(self, alert_id: str) -> str:
        alerts = self._load("alerts_json")
        aid = str(alert_id or "").strip().lower()
        if aid not in alerts:
            return json.dumps({"error": "unknown alert_id"})
        return json.dumps(alerts[aid], sort_keys=True, separators=(",", ":"))

    @gl.public.view
    def list_alerts(self, watch_id: str) -> str:
        """All alerts, newest first; pass an empty watch_id for every watch."""
        alerts = self._load("alerts_json")
        wid = str(watch_id or "").strip().lower()
        rows = [a for a in alerts.values() if not wid or a.get("watch_id") == wid]
        rows.sort(
            key=lambda a: int(str(a.get("alert_id", "alert-0")).split("-")[-1]),
            reverse=True,
        )
        return json.dumps(rows, sort_keys=True, separators=(",", ":"))

    @gl.public.view
    def get_stats(self) -> str:
        watches = self._load("watches_json")
        alerts = self._load("alerts_json")
        active = sum(1 for w in watches.values() if w.get("status") == STATUS_ACTIVE)
        checks = sum(int(w.get("checks", 0)) for w in watches.values())
        material = sum(1 for a in alerts.values() if a.get("material"))
        return json.dumps(
            {
                "watches": len(watches),
                "active": active,
                "checks": checks,
                "alerts": len(alerts),
                "material_alerts": material,
                "cosmetic_alerts": len(alerts) - material,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @gl.public.view
    def get_owner(self) -> str:
        return self.owner

    @gl.public.view
    def get_criteria_template(self) -> str:
        return DEFAULT_CRITERIA
