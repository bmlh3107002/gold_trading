"""Analyst Tin tức (GĐ3 bước 6 — NEWS-01..04; 3-C10; DEC-08). Thiết kế: ``32-news-analyst.md``.

Hai phần tách rời:

1. **Luồng đọc tin (``NewsLlmWorker``)** chạy ở **luồng riêng**, mỗi phút: chọn tin mới (gộp
   trùng — GĐ1 ``news_stories``), lọc trước bằng luật (tiếng Anh + có thực thể liên quan vàng —
   NEWS-01/02), kiểm ngân sách, gọi Claude (``news_llm.extract``), ghi sổ. **Không bao giờ** gọi
   Claude trong nhịp 2 giây của orchestrator (làn nhanh chậm > 10 giây → Safety chặn).
2. **Analyst (``compute``)** — toàn cục, chỉ đọc: tổng hợp các kết quả **đã có trước ``as_of``** của
   tin trong 24 giờ: đếm theo chiều tác động, điểm tông (không phải xác suất), ``NEWS_SHOCK`` khi có
   tin tác động cao + bất ngờ trong 2 giờ. Kết quả có cờ injection / trích dẫn không có trong
   bài → **không dùng**. Chưa cấu hình Claude → ``MISSING``; hết ngân sách còn tin chưa đọc →
   cờ + trần 0,5.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from gold_trading.analysts import news_llm as L
from gold_trading.analysts.framework import GLOBAL_SCOPE, InputCheck, assess, build_output
from gold_trading.common.time import utcnow
from gold_trading.contracts.analyst import AnalystOutput
from gold_trading.ingestion import news as N
from gold_trading.ingestion.news_tags import tag_record

log = logging.getLogger("gold_trading.analysts")

ANALYST_ID = "news"
VERSION = "news-1.0.0"
HANDLER_VERSION = "news-job-1"
RELEVANT = frozenset({"FED", "RATES", "INFLATION", "LABOR", "GOLD", "USD", "FISCAL",
                      "GEOPOLITICS"})
PROCESS_WINDOW = timedelta(hours=48)   # chỉ đọc tin thấy lần đầu trong 48 giờ (không đọc lịch sử)
LOOKBACK = timedelta(hours=24)         # analyst tổng hợp tin 24 giờ
SHOCK_WINDOW = timedelta(hours=2)
PENDING_GRACE = timedelta(minutes=10)
MAX_ATTEMPTS = 3
RETRY_BASE = timedelta(minutes=5)
MAX_PER_CYCLE = 5
CYCLE = timedelta(seconds=60)
TTL = timedelta(minutes=15)
DEGRADED_CAP = 0.5
SETTLE = timedelta(seconds=5)
FALLBACK_GRACE = timedelta(seconds=60)
WEIGHT = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
SIGN = {"BULLISH": 1, "BEARISH": -1, "NEUTRAL": 0, "UNCLEAR": 0}
FINAL = frozenset({"OK", "REFUSED", "INVALID_OUTPUT", "TRUNCATED"})


def story_key(s: N.NewsStory) -> str:
    r = s.root
    fp = r.payload.get("content_fingerprint") or r.record_id
    return f"{r.source}:{r.logical_key}:{fp}"[:256]


def relevance(s: N.NewsStory) -> tuple[bool, str]:
    tags = tag_record(s.root)
    if tags.language != "en":
        return False, f"LANGUAGE_{tags.language.upper()}"
    if not (set(tags.groups) & RELEVANT):
        return False, "NOT_RELEVANT"
    return True, ",".join(sorted(set(tags.groups) & RELEVANT))


def _text(s: N.NewsStory) -> tuple[str, str]:
    p = s.root.payload
    return str(p.get("title", "")), str(p.get("summary", ""))


def suspect(s: N.NewsStory) -> bool:
    return "SUSPECT_INSTRUCTIONS" in (s.root.payload.get("flags") or [])


# ================================================================ 1. Luồng đọc tin

class NewsLlmWorker:
    """Gọi Claude cho tin mới. ``client_factory()`` → client SDK (None = chưa cấu hình)."""

    def __init__(self, *, record_store, llm_store, client_factory: Callable[[], Any],
                 model: str = L.DEFAULT_MODEL, budget: L.Budget | None = None,
                 on_result: Callable[[datetime], object] | None = None,
                 now: Callable[[], datetime] = utcnow) -> None:
        self.record_store = record_store
        self.llm_store = llm_store
        self.client_factory = client_factory
        self.model = model
        self.budget = budget or L.Budget()
        self.on_result = on_result
        self._now = now
        self._client = None
        self._disabled: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def disabled_reason(self) -> str | None:
        return self._disabled

    def candidates(self, now: datetime) -> list[tuple[N.NewsStory, int]]:
        """(tin, lần thử kế tiếp) cần gọi — mới nhất trước."""
        out = []
        for s in N.news_stories(self.record_store, now,
                                lookback=PROCESS_WINDOW + timedelta(days=1)):
            if now - s.first_seen_at > PROCESS_WINDOW:
                continue
            ok, _ = relevance(s)
            title, summary = _text(s)
            if not ok or len(L.article_text(title, summary)) > L.MAX_ARTICLE_CHARS:
                continue
            calls = [c for c in self.llm_store.calls_for(story_key(s))
                     if c.prompt_version == L.PROMPT_VERSION and c.model == self.model]
            if any(c.status in FINAL for c in calls) or len(calls) >= MAX_ATTEMPTS:
                continue
            if calls and now - calls[-1].created_at < RETRY_BASE * (2 ** (len(calls) - 1)):
                continue
            out.append((s, len(calls) + 1))
        return sorted(out, key=lambda x: x[0].first_seen_at, reverse=True)

    def run_once(self, now: datetime | None = None) -> dict[str, int]:
        now = now or self._now()
        stats = {"called": 0, "ok": 0, "skipped_budget": 0}
        if self._disabled:
            return stats
        if self._client is None:
            self._client = self.client_factory()
            if self._client is None:
                self._disabled = "LLM_NOT_CONFIGURED"
                return stats
        for s, attempt in self.candidates(now)[:MAX_PER_CYCLE]:
            title, summary = _text(s)
            need = L.worst_case(len(L.article_text(title, summary)))
            why = self.budget.allows(self.llm_store, now, need)
            if why:
                stats["skipped_budget"] += 1
                log.warning("News: không gọi Claude (%s)", why)
                break
            p = s.root.payload
            row = L.extract(self._client, model=self.model, story_key=story_key(s),
                            attempt=attempt, now=self._now(), source=s.root.source,
                            published=str(p.get("published_at") or p.get("first_seen_at")),
                            title=title, summary=summary)
            self.llm_store.append(row)
            stats["called"] += 1
            stats["ok"] += row.status == "OK"
            if row.error_code in L.FATAL_ERRORS:
                self._disabled = row.error_code          # khóa sai / hết hạn mức → dừng gọi
                log.error("News: dừng gọi Claude (%s)", row.error_code)
                break
        if stats["called"] and self.on_result is not None:
            self.on_result(self._now())
        return stats

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("News: luồng đọc tin lỗi, thử lại sau")
            if self._stop.wait(CYCLE.total_seconds()):
                return

    def start(self) -> None:
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="news-llm", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None


# ================================================================ 2. Analyst

def _usable(row: L.CallRow, s: N.NewsStory) -> tuple[bool, list[str]]:
    title, summary = _text(s)
    problems = L.validate(row.result or {}, L.article_text(title, summary))
    if (row.result or {}).get("injection_suspected") is True or suspect(s):
        problems.append("INJECTION_SUSPECTED")
    return not problems, problems


def compute(record_store, llm_store, as_of: datetime, *, llm_status: str | None,
            model: str = L.DEFAULT_MODEL, budget: L.Budget | None = None,
            correlation_id: str = "news") -> AnalystOutput:
    """``llm_status``: None = Claude sẵn sàng; ngược lại mã lý do (vd. ``LLM_NOT_CONFIGURED``)."""
    budget = budget or L.Budget()
    # Claude là đầu vào TÙY CHỌN: tắt (chế độ miễn phí) → vẫn liệt kê tin theo luật, không đánh giá.
    checks = [InputCheck("claude", None if llm_status else as_of, timedelta(days=3650),
                         required=False)]
    a = assess(checks, as_of)
    stories = [s for s in N.news_stories(record_store, as_of, lookback=LOOKBACK + timedelta(days=1))
               if as_of - LOOKBACK <= s.first_seen_at <= as_of]
    q_flags: set[str] = set()
    if llm_status:
        q_flags.update({f"LLM:{llm_status}", "RULES_ONLY"})
    items: list[dict[str, Any]] = []
    plain: list[dict[str, Any]] = []
    digest_rows = []
    pending = unprocessed = excluded = 0
    for s in stories:
        ok, why = relevance(s)
        if not ok:
            continue
        calls = [c for c in llm_store.calls_for(story_key(s))
                 if c.created_at <= as_of and c.prompt_version == L.PROMPT_VERSION
                 and c.model == model]
        done = next((c for c in reversed(calls) if c.status == "OK"), None)
        if done is None:
            p0 = s.root.payload
            plain.append({"story_key": story_key(s), "source": s.root.source,
                          "title": p0.get("title"), "url": p0.get("url"),
                          "first_seen_at": s.first_seen_at, "topics": why,
                          "suspect_instructions": suspect(s), "assessed": False})
            if llm_status:
                continue                       # chế độ miễn phí: không tính là "chưa xử lý"
            if as_of - s.first_seen_at <= PENDING_GRACE and len(calls) < MAX_ATTEMPTS:
                pending += 1
            else:
                unprocessed += 1
            continue
        usable, problems = _usable(done, s)
        digest_rows.append([done.call_id, problems])
        if not usable:
            excluded += 1
            q_flags.update(f"NEWS_EXCLUDED:{p}" for p in problems)
            continue
        r = done.result
        p = s.root.payload
        items.append({"story_key": story_key(s), "source": s.root.source,
                      "sources": list(s.sources),
                      "title": p.get("title"), "url": p.get("url"),
                      "first_seen_at": s.first_seen_at, "topics": why,
                      **{k: r[k] for k in ("gold_impact", "usd_impact", "fed_stance", "impact",
                                           "novelty", "horizon", "evidence_quote", "summary_vi")},
                      "model": done.served_model or done.model,
                      "prompt_version": done.prompt_version, "analyzed_at": done.created_at,
                      "assessed": True})
    items.sort(key=lambda x: x["first_seen_at"], reverse=True)
    counts = {k: sum(1 for i in items if i["gold_impact"] == k) for k in L.GOLD_IMPACT}
    tone = sum(SIGN[i["gold_impact"]] * WEIGHT[i["impact"]] for i in items)
    shock = [i for i in items if i["impact"] == "HIGH" and i["novelty"] == "SURPRISE"
             and as_of - i["first_seen_at"] <= SHOCK_WINDOW]
    plain.sort(key=lambda x: x["first_seen_at"], reverse=True)
    confidence = DEGRADED_CAP if llm_status else 1.0
    drivers = [f"NEWS_ITEMS:{len(items)}", f"NEWS_UNASSESSED:{len(plain)}"]
    risk_flags: set[str] = set()
    if unprocessed:
        q_flags.add(f"NEWS_UNPROCESSED:{unprocessed}")
        confidence = DEGRADED_CAP
    if pending:
        q_flags.add(f"NEWS_PENDING:{pending}")
    if excluded:
        drivers.append(f"NEWS_EXCLUDED:{excluded}")
    if shock:
        risk_flags.add("NEWS_SHOCK")
        drivers.append("NEWS_SHOCK")
    features = {
        "mode": "RULES_ONLY" if llm_status else "LLM",
        "items": items[:10],
        "unassessed": plain[:10],
        "counts": counts,
        "tone_score": tone if not llm_status else None,
        "tone_note": "tổng (+1 hỗ trợ / −1 cản vàng) × mức tác động 1–3 — không phải xác suất",
        "news_shock": bool(shock),
        "pending": pending, "unprocessed": unprocessed, "excluded": excluded,
        "model": model, "prompt_version": L.PROMPT_VERSION,
        "budget": budget.status(llm_store, as_of),
        "source_note": "Tin chính thức: Federal Reserve, U.S. Department of the Treasury",
    }
    return build_output(analyst_id=ANALYST_ID, version=VERSION, scope=GLOBAL_SCOPE, as_of=as_of,
                        expires_at=as_of + TTL, correlation_id=correlation_id, assessment=a,
                        digest_of={"rows": digest_rows, "stories": [story_key(s) for s in stories],
                                   "pending": pending, "unprocessed": unprocessed,
                                   "llm": llm_status},
                        features=features, drivers=drivers, risk_flags=risk_flags,
                        quality_flags=q_flags, confidence=confidence)


class NewsAnalyst:
    def __init__(self, record_store, llm_store, out_store, *, llm_status: Callable[[], str | None],
                 model: str = L.DEFAULT_MODEL, budget: L.Budget | None = None) -> None:
        self.record_store = record_store
        self.llm_store = llm_store
        self.out_store = out_store
        self.llm_status = llm_status
        self.model = model
        self.budget = budget or L.Budget()

    def current(self, now: datetime):
        got = self.out_store.latest_scoped(ANALYST_ID, GLOBAL_SCOPE, known_by=now)
        return got if got is not None and got.output.version == VERSION else None

    def run_at(self, as_of: datetime, now: datetime, correlation_id: str = "news") -> bool:
        out = compute(self.record_store, self.llm_store, as_of, llm_status=self.llm_status(),
                      model=self.model, budget=self.budget, correlation_id=correlation_id)
        return self.out_store.append_scoped(out, GLOBAL_SCOPE, computed_at=now)

    def after_llm(self, now: datetime) -> bool:
        return self.run_at(now - SETTLE, now, "news:llm")

    def ensure_fresh(self, now: datetime) -> bool:
        got = self.current(now)
        if got is not None and got.output.expires_at > now - FALLBACK_GRACE:
            return False
        return self.run_at(now - SETTLE, now, "news:fallback")


def news_handler(analyst: NewsAnalyst):
    """Job ``NEWS`` (tin mới, kết quả hết hạn): chỉ tính lại tổng hợp — **không** gọi Claude."""
    from gold_trading.orchestrator.dispatcher import Handler

    def run(e, now: datetime) -> str | None:
        got = analyst.current(now)
        if got is not None and got.output.is_valid_at(now) and got.output.as_of >= e.known_at:
            return "news:unchanged"
        as_of = min(now, max(now - SETTLE, e.known_at))
        return "news:stored" if analyst.run_at(as_of, now, e.correlation_id or "news") \
            else "news:unchanged"

    return Handler(HANDLER_VERSION, run, deadline=timedelta(seconds=30), max_attempts=3)


def client_from_env(env) -> Callable[[], Any]:
    """Client SDK nếu có ``ANTHROPIC_API_KEY`` (không bao giờ ghi / in khóa); không có → None."""
    def make():
        if not (env.get("ANTHROPIC_API_KEY") or "").strip():
            return None
        import anthropic
        return anthropic.Anthropic(max_retries=2, timeout=L.TIMEOUT_S)
    return make
