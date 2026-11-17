"""
智汇研途 · 严谨性内核（Rigor Kernel）

核心承诺：**只有被独立复核且两次答案一致的结论才会进入回答正文**。

三道关卡
--------
① 溯源   Tracing    —— 每条结论都带来源库、API 端点、持久标识符（DOI / 国标标准号 / 术语编码）、抓取时间与可点击原文链接。
② 复核   Re-check   —— 拿到结果后，换一条**独立通道**重新问一次「是否真的存在这篇文献 / 这个译法」，
                        例如检索接口 → DOI 注册记录精确查询 → 另一个学术库按 DOI 反查。
③ 门控   Gate       —— 结构化字段逐项比对（标题相似度、年份、作者、DOI）；
                        所有独立通道都同意才标记 verified，任一冲突或无法复核就剔除出结论区。

精确度策略
----------
* 归一化：NFKC → 去 HTML → 去变音符 → 去标点/停用词 → 折叠空白
* 相似度：SequenceMatcher 与 token Jaccard 加权，阈值 0.88（可配）
* 去重：按 DOI，再按归一化标题
* 过滤：空标题、异常年份、与查询毫无词汇重叠的结果
* 撤稿检测：Crossref 的 update-to / is-retracted-by 关系 → 直接判 disputed
* 宁缺毋滥：无法复核的条目进「未通过核验」区，绝不冒充确定结论

环境变量
--------
ZHIHUI_RIGOR_CHECKS        需要的独立复核通道数（默认 2，范围 1~3）
ZHIHUI_RIGOR_THRESHOLD     标题一致阈值（默认 0.88）
ZHIHUI_RIGOR_MAX_ITEMS     最多复核候选数（默认 8）
ZHIHUI_RIGOR_CACHE_TTL     复核结果缓存秒数（默认 3600）
ZHIHUI_BACKTRANSLATION     是否启用回译复核（默认 1）
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import quote

from security import (
    clean_text, fence, safe_get, safe_post, safe_json, redact,
    UnsafeUpstream, audit, strip_role_markers,
)

# ---------------------------------------------------------------- 策略常量

CHECKS_REQUIRED = max(1, min(3, int(os.getenv("ZHIHUI_RIGOR_CHECKS", "2"))))
TITLE_THRESHOLD = float(os.getenv("ZHIHUI_RIGOR_THRESHOLD", "0.88"))
MAX_ITEMS = max(1, min(20, int(os.getenv("ZHIHUI_RIGOR_MAX_ITEMS", "8"))))
CACHE_TTL = int(os.getenv("ZHIHUI_RIGOR_CACHE_TTL", "3600"))
BACKTRANSLATION = os.getenv("ZHIHUI_BACKTRANSLATION", "1").strip().lower() in ("1", "true", "yes")
DEADLINE = float(os.getenv("ZHIHUI_RIGOR_DEADLINE", "16"))

POLICY = {
    "checks_required": CHECKS_REQUIRED,
    "title_similarity_threshold": TITLE_THRESHOLD,
    "max_items": MAX_ITEMS,
    "deadline_sec": DEADLINE,
    "rule": "只有 N 条独立通道对同一结构化记录给出一致答案，才进入结论区；冲突或无法复核一律剔除并公示。",
    "fabrication": "答案正文只由已核验记录组装，模型不得补充任何未提供的事实性内容。",
}

# ---------------------------------------------------------------- 归一化与比对

_HTML_TAG = re.compile(r"<[^>]+>")
_PUNCT = re.compile(r"[^\w\s\u4e00-\u9fff]", re.UNICODE)
_WS = re.compile(r"\s+")
_STOPWORDS = frozenset({
    "a", "an", "the", "of", "on", "in", "for", "and", "to", "with", "by",
    "from", "at", "is", "are", "be", "using", "based", "study", "studies",
    "towards", "toward", "via", "its", "their", "our", "new", "novel",
})


def norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = _HTML_TAG.sub(" ", s).lower()
    # 去掉拉丁变音符，但保留中文
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


def norm_title(s: str) -> str:
    return norm_text(s)


def norm_doi(s: str) -> str:
    d = str(s or "").strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    d = re.sub(r"^doi:\s*", "", d)
    return d.strip().strip(".,;")


def tokens(s: str) -> set[str]:
    return {t for t in norm_text(s).split() if t and t not in _STOPWORDS}


def similarity(a: str, b: str) -> float:
    """标题相似度：字符序列比 + token Jaccard 加权，抗词序与标点差异。"""
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    seq = difflib.SequenceMatcher(None, na, nb).ratio()
    ta, tb = tokens(na), tokens(nb)
    jac = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    return round(0.6 * seq + 0.4 * jac, 4)


def year_ok(y: str) -> bool:
    try:
        v = int(str(y).strip()[:4])
        return 1500 <= v <= datetime.now().year + 1
    except Exception:
        return False


def relevance(query: str, title: str) -> float:
    qt, tt = tokens(query), tokens(title)
    if not qt or not tt:
        return 0.0
    return round(len(qt & tt) / len(qt), 3)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def source_ref(name: str, url: str, endpoint: str = "", identifier: str = "", note: str = "") -> dict:
    return {
        "name": name,
        "url": url,
        "endpoint": endpoint,
        "identifier": identifier,
        "retrieved_at": _now(),
        "note": note,
    }


# ---------------------------------------------------------------- 复核结果缓存

_DB_DIR = os.getenv("ZHIHUI_DATA_DIR") or os.path.join(os.path.expanduser("~"), "zhihui-data")
_DB_FILE = os.path.join(_DB_DIR, "rigor.db")
_DB_LOCK = threading.Lock()


def _cache_get(key: str):
    try:
        with _DB_LOCK:
            conn = sqlite3.connect(_DB_FILE, timeout=2)
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS rigor_cache (k TEXT PRIMARY KEY, payload TEXT, ts INTEGER)"
                )
                row = conn.execute("SELECT payload, ts FROM rigor_cache WHERE k=?", (key,)).fetchone()
            finally:
                conn.close()
        if row and time.time() - int(row[1]) < CACHE_TTL:
            return json.loads(row[0])
    except Exception:
        pass
    return None


def _cache_put(key: str, payload: dict):
    try:
        os.makedirs(_DB_DIR, exist_ok=True)
        with _DB_LOCK:
            conn = sqlite3.connect(_DB_FILE, timeout=2)
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS rigor_cache (k TEXT PRIMARY KEY, payload TEXT, ts INTEGER)"
                )
                conn.execute(
                    "INSERT INTO rigor_cache (k,payload,ts) VALUES (?,?,?) "
                    "ON CONFLICT(k) DO UPDATE SET payload=excluded.payload, ts=excluded.ts",
                    (key, json.dumps(payload, ensure_ascii=False), int(time.time())),
                )
                conn.commit()
            finally:
                conn.close()
    except Exception:
        pass


# ---------------------------------------------------------------- 发现通道（Discovery）

def _disc_crossref(q: str, n: int) -> list[dict]:
    data = safe_json(
        "https://api.crossref.org/works",
        params={"query.bibliographic": q, "rows": n},
        headers={"User-Agent": "ZhihuiYantu-Rigor/2.0 (mailto:local@localhost)"},
    )
    out = []
    for it in (data.get("message") or {}).get("items", []):
        year = ""
        for k in ("published-print", "published-online", "issued"):
            p = (it.get(k) or {}).get("date-parts")
            if p and p[0] and p[0][0]:
                year = str(p[0][0]); break
        out.append({
            "source": "Crossref", "title": (it.get("title") or [""])[0],
            "authors": ", ".join(f"{a.get('given','')} {a.get('family','')}".strip()
                                 for a in (it.get("author") or [])[:6]),
            "year": year, "doi": norm_doi(it.get("DOI", "")),
            "url": f"https://doi.org/{norm_doi(it.get('DOI',''))}" if it.get("DOI") else "",
        })
    return out


def _disc_openalex(q: str, n: int) -> list[dict]:
    data = safe_json("https://api.openalex.org/works", params={"search": q, "per-page": n})
    out = []
    for it in data.get("results", []):
        doi = norm_doi(it.get("doi") or "")
        out.append({
            "source": "OpenAlex", "title": it.get("title") or "",
            "authors": ", ".join(a.get("author", {}).get("display_name", "")
                                 for a in (it.get("authorships") or [])[:6]),
            "year": str(it.get("publication_year") or ""), "doi": doi,
            "url": it.get("doi") or "",
        })
    return out


def _disc_europepmc(q: str, n: int) -> list[dict]:
    data = safe_json(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": q, "format": "json", "pageSize": n},
    )
    out = []
    for it in (data.get("resultList") or {}).get("result", []):
        doi = norm_doi(it.get("doi", ""))
        out.append({
            "source": "Europe PMC", "title": it.get("title", ""),
            "authors": it.get("authorString", ""), "year": str(it.get("pubYear", "")),
            "doi": doi, "url": f"https://doi.org/{doi}" if doi else "",
        })
    return out


def _disc_doaj(q: str, n: int) -> list[dict]:
    data = safe_json(
        f"https://doaj.org/api/search/articles/{quote(q, safe='')}",
        params={"pageSize": n},
    )
    out = []
    for it in data.get("results", []):
        b = it.get("bibjson", {}) or {}
        doi = ""
        for ident in b.get("identifier", []) or []:
            if str(ident.get("type", "")).lower() == "doi":
                doi = norm_doi(ident.get("id") or ""); break
        links = b.get("link") or []
        out.append({
            "source": "DOAJ", "title": b.get("title") or "",
            "authors": ", ".join(a.get("name", "") for a in (b.get("author") or [])[:6]
                                 if isinstance(a, dict)),
            "year": str(b.get("year") or ""), "doi": doi,
            "url": (links[0].get("url") if links and isinstance(links[0], dict) else "")
                   or (f"https://doi.org/{doi}" if doi else ""),
        })
    return out


DISCOVERY = {
    "Crossref": _disc_crossref,
    "OpenAlex": _disc_openalex,
    "Europe PMC": _disc_europepmc,
    "DOAJ": _disc_doaj,
}


def discover(query: str, per_source: int = 4) -> tuple[list[dict], list[str], list[str]]:
    """并行检索 4 个独立学术库；返回 (原始条目, 成功源, 失败源)。"""
    items, ok, fail = [], [], []
    ex = ThreadPoolExecutor(max_workers=len(DISCOVERY))
    futs = {ex.submit(fn, query, per_source): name for name, fn in DISCOVERY.items()}
    try:
        for f in as_completed(futs, timeout=DEADLINE):
            name = futs[f]
            try:
                got = f.result()
                items.extend(got)
                ok.append(name)
            except Exception:
                fail.append(name)
    except Exception:
        pass
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    for name in DISCOVERY:
        if name not in ok and name not in fail:
            fail.append(name)
    return items, ok, fail


def cluster(items: list[dict], query: str) -> list[dict]:
    """去重合并（DOI 优先、标题次之），做基础质量过滤，按相关度 + 证据数排序。"""
    groups: list[dict] = []
    for it in items:
        title = clean_text(strip_role_markers(it.get("title") or ""), 500)
        if len(norm_title(title)) < 6:
            continue
        y = str(it.get("year") or "").strip()[:4]
        if y and not year_ok(y):
            continue
        doi = norm_doi(it.get("doi") or "")
        hit = None
        for g in groups:
            if doi and g["doi"] and doi == g["doi"]:
                hit = g; break
            if similarity(g["title"], title) >= 0.93 and (not y or not g["year"] or y == g["year"]):
                hit = g; break
        if hit is None:
            hit = {
                "title": title, "authors": it.get("authors") or "", "year": y,
                "doi": doi, "url": it.get("url") or "", "origin_sources": [],
                "sources": [], "discovery_hits": 0,
            }
            groups.append(hit)
        hit["discovery_hits"] += 1
        src = it.get("source") or "unknown"
        if src not in hit["origin_sources"]:
            hit["origin_sources"].append(src)
        hit["sources"].append(source_ref(
            src, it.get("url") or "", identifier=doi,
            note="发现通道： bibliographic 检索",
        ))
        # 优先保留信息更全的记录
        if not hit["doi"] and doi:
            hit["doi"] = doi
        if not hit["authors"] and it.get("authors"):
            hit["authors"] = it["authors"]
        if not hit["url"] and it.get("url"):
            hit["url"] = it["url"]

    for g in groups:
        g["relevance"] = relevance(query, g["title"])
        # 多个发现源指向同一记录，本身是支持性证据（但不替代独立复核）
        g["support"] = len(set(g["origin_sources"]))
    # 硬过滤：与查询完全无词汇重叠
    groups = [g for g in groups if g["relevance"] > 0 or g["doi"]]
    groups.sort(key=lambda g: (g["support"], g["relevance"], bool(g["doi"])), reverse=True)
    return groups[:MAX_ITEMS]


# ---------------------------------------------------------------- 独立复核通道（Verification）

def _check_result(channel: str, endpoint: str, verdict: str, detail: str,
                  sim: float = 0.0, year: str = "", url: str = "") -> dict:
    return {
        "channel": channel, "endpoint": endpoint, "verdict": verdict,
        "detail": redact(detail)[:300], "title_similarity": sim,
        "year": year, "url": url, "checked_at": _now(),
    }


def _compare(cand: dict, title: str, year: str, channel: str, endpoint: str, url: str = "") -> dict:
    """把复核通道返回的记录与候选逐字段比对，产出 agree / conflict / unavailable。"""
    sim = similarity(cand["title"], title)
    cy = str(cand.get("year") or "")[:4]
    ry = str(year or "")[:4]
    year_conflict = bool(cy and ry and cy != ry)
    if sim < TITLE_THRESHOLD:
        return _check_result(channel, endpoint, "conflict",
                             f"标题不一致（相似度 {sim} < {TITLE_THRESHOLD}）：复核返回「{clean_text(title,120)}」",
                             sim, ry, url)
    if year_conflict:
        return _check_result(channel, endpoint, "conflict",
                             f"年份冲突：候选 {cy} / 复核 {ry}", sim, ry, url)
    return _check_result(channel, endpoint, "agree",
                         f"标题相似度 {sim}；年份 {cy or '—'} / {ry or '—'} 一致", sim, ry, url)


def _v_crossref_doi(cand: dict) -> dict:
    """复核通道 1：直接查 DOI 注册记录（与发现用的 bibliographic 搜索完全不同的端点）。"""
    ch, url = "Crossref DOI 注册记录", f"https://api.crossref.org/works/{quote(cand['doi'], safe='/.-_')}"
    try:
        r = safe_get(url, headers={"User-Agent": "ZhihuiYantu-Rigor/2.0 (mailto:local@localhost)"})
        if r.status_code == 404:
            return _check_result(ch, url, "conflict", "DOI 在 Crossref 中不存在（404）", url=url)
        r.raise_for_status()
        msg = r.json().get("message") or {}
        title = (msg.get("title") or [""])[0]
        year = ""
        for k in ("published-print", "published-online", "issued"):
            p = (msg.get(k) or {}).get("date-parts")
            if p and p[0] and p[0][0]:
                year = str(p[0][0]); break
        res = _compare(cand, title, year, ch, url, url)
        # 撤稿 / 更正关系检测
        for upd in (msg.get("update-to") or []) + (msg.get("relation", {}) or {}).get("is-retracted-by", []):
            if isinstance(upd, dict) and "retract" in str(upd.get("type", "")).lower():
                res["verdict"] = "conflict"
                res["detail"] += "；⚠ 该记录存在撤稿/更正关系"
        return res
    except Exception as e:
        return _check_result(ch, url, "unavailable", f"通道不可用：{e.__class__.__name__}", url=url)


def _v_openalex_doi(cand: dict) -> dict:
    """复核通道 2：另一家学术索引按 DOI 精确反查。"""
    ch, url = "OpenAlex DOI 精确反查", "https://api.openalex.org/works"
    try:
        data = safe_json(url, params={"filter": f"doi:{cand['doi']}", "per-page": 1})
        rs = data.get("results") or []
        if not rs:
            return _check_result(ch, url, "conflict", "OpenAlex 中无此 DOI 记录", url=url)
        it = rs[0]
        return _compare(cand, it.get("title") or "", str(it.get("publication_year") or ""),
                        ch, url, it.get("doi") or "")
    except Exception as e:
        return _check_result(ch, url, "unavailable", f"通道不可用：{e.__class__.__name__}", url=url)


def _v_crossref_title(cand: dict) -> dict:
    """复核通道 3（无 DOI 时启用）：Crossref 按精确标题检索。"""
    ch, url = "Crossref 标题精确检索", "https://api.crossref.org/works"
    try:
        data = safe_json(url, params={"query.title": cand["title"], "rows": 3},
                         headers={"User-Agent": "ZhihuiYantu-Rigor/2.0 (mailto:local@localhost)"})
        its = (data.get("message") or {}).get("items", [])
        if not its:
            return _check_result(ch, url, "conflict", "Crossref 中检索不到该标题", url=url)
        best = max(its, key=lambda x: similarity(cand["title"], (x.get("title") or [""])[0]))
        year = ""
        for k in ("published-print", "published-online", "issued"):
            p = (best.get(k) or {}).get("date-parts")
            if p and p[0] and p[0][0]:
                year = str(p[0][0]); break
        return _compare(cand, (best.get("title") or [""])[0], year, ch, url,
                        f"https://doi.org/{norm_doi(best.get('DOI',''))}" if best.get("DOI") else "")
    except Exception as e:
        return _check_result(ch, url, "unavailable", f"通道不可用：{e.__class__.__name__}", url=url)


def _v_europepmc_title(cand: dict) -> dict:
    """复核通道 4（无 DOI 时启用）：Europe PMC 按 TITLE: 字段精确检索。"""
    ch, url = "Europe PMC TITLE 精确检索", "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    try:
        data = safe_json(url, params={"query": f'TITLE:"{cand["title"]}"', "format": "json", "pageSize": 3})
        its = (data.get("resultList") or {}).get("result", [])
        if not its:
            return _check_result(ch, url, "conflict", "Europe PMC 中检索不到该标题", url=url)
        best = max(its, key=lambda x: similarity(cand["title"], x.get("title") or ""))
        return _compare(cand, best.get("title") or "", str(best.get("pubYear") or ""), ch, url)
    except Exception as e:
        return _check_result(ch, url, "unavailable", f"通道不可用：{e.__class__.__name__}", url=url)


def _verify_one(cand: dict) -> dict:
    """对单条候选做 N 条独立通道复核。"""
    if cand.get("doi"):
        channels = [_v_crossref_doi, _v_openalex_doi, _v_crossref_title]
    else:
        channels = [_v_crossref_title, _v_europepmc_title]
    checks = []
    ex = ThreadPoolExecutor(max_workers=len(channels))
    futs = [ex.submit(fn, cand) for fn in channels]
    try:
        for f in as_completed(futs, timeout=DEADLINE):
            try:
                checks.append(f.result())
            except Exception as e:
                checks.append(_check_result("unknown", "", "unavailable", f"异常：{e.__class__.__name__}"))
    except Exception:
        pass
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    # 未按时返回的通道也记为 unavailable
    if len(checks) < len(channels):
        for i in range(len(checks), len(channels)):
            checks.append(_check_result(f"channel-{i}", "", "unavailable", "复核超时"))

    agree = [c for c in checks if c["verdict"] == "agree"]
    conflict = [c for c in checks if c["verdict"] == "conflict"]
    unavailable = [c for c in checks if c["verdict"] == "unavailable"]

    reason = ""
    if conflict:
        verdict = "disputed"
        reason = "；".join(c["detail"] for c in conflict)[:400]
    elif len(agree) >= CHECKS_REQUIRED:
        verdict = "verified"
    else:
        verdict = "unverifiable"
        reason = f"仅 {len(agree)}/{CHECKS_REQUIRED} 条通道确认" + (
            f"（{len(unavailable)} 条通道不可用）" if unavailable else "")

    sims = [c["title_similarity"] for c in agree] or [0.0]
    conf = 0.0
    if verdict == "verified":
        conf = min(1.0, round(
            0.45 + 0.12 * min(len(agree), 3) + 0.15 * (sum(sims) / len(sims))
            + 0.10 * (1 if cand["doi"] else 0)
            + 0.06 * min(cand.get("support", 1), 3), 3))

    return {
        "id": "L" + hashlib.sha1((cand["doi"] or norm_title(cand["title"])).encode()).hexdigest()[:8],
        "kind": "literature",
        "claim": cand["title"],
        "fields": {
            "title": cand["title"], "authors": cand["authors"], "year": cand["year"],
            "doi": cand["doi"], "url": cand["url"],
            "relevance": cand.get("relevance", 0),
            "discovery_sources": cand["origin_sources"],
        },
        "sources": cand["sources"] + [
            source_ref(c["channel"], c["url"] or c["endpoint"],
                       endpoint=c["endpoint"], note=f"独立复核：{c['verdict']}")
            for c in checks if c["verdict"] == "agree"
        ],
        "checks": checks,
        "agreement": f"{len(agree)}/{len(checks)}",
        "agreement_required": CHECKS_REQUIRED,
        "verdict": verdict,
        "confidence": conf,
        "reject_reason": reason,
    }


# ---------------------------------------------------------------- 对外：文献核验

def verify_literature(query: str, per_source: int = 4, use_cache: bool = True) -> dict:
    """完整流程：发现 → 聚类 → 独立复核 → 一致性门控。"""
    t0 = time.time()
    q = clean_text(query, 300)
    if not q:
        return _empty_report("literature", q, "查询为空")
    ck = "lit:" + hashlib.sha256(f"{q}|{per_source}|{CHECKS_REQUIRED}".encode()).hexdigest()[:24]
    if use_cache:
        hit = _cache_get(ck)
        if hit:
            hit["cached"] = True
            hit["elapsed_ms"] = int((time.time() - t0) * 1000)
            return hit

    raw, ok, fail = discover(q, per_source)
    candidates = cluster(raw, q)
    verified, rejected = [], []
    if candidates:
        ex = ThreadPoolExecutor(max_workers=min(4, len(candidates)))
        futs = [ex.submit(_verify_one, c) for c in candidates]
        res = []
        try:
            for f in as_completed(futs, timeout=DEADLINE + 6):
                try:
                    res.append(f.result())
                except Exception as e:
                    res.append({"kind": "literature", "verdict": "unverifiable",
                                "claim": "", "reject_reason": f"复核异常：{e.__class__.__name__}",
                                "checks": [], "sources": [], "confidence": 0, "agreement": "0/0"})
        except Exception:
            pass
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        for r in res:
            (verified if r["verdict"] == "verified" else rejected).append(r)
        verified.sort(key=lambda r: (-r["confidence"], -r["fields"].get("relevance", 0)))

    report = {
        "ok": True,
        "kind": "literature",
        "query": q,
        "policy": POLICY,
        "verified": verified,
        "rejected": rejected,
        "summary": {
            "discovered": len(raw),
            "clusters": len(candidates),
            "verified": len(verified),
            "rejected": len(rejected),
            "sources_ok": ok,
            "sources_fail": fail,
            "checks_required": CHECKS_REQUIRED,
            "threshold": TITLE_THRESHOLD,
            "gate": "PASS" if verified else "NO_VERIFIED_CLAIM",
        },
        "sources": _unique_sources(verified + rejected),
        "generated_at": _now(),
        "elapsed_ms": int((time.time() - t0) * 1000),
        "cached": False,
    }
    if use_cache and verified:
        _cache_put(ck, report)
    audit("verify.literature", user_input=q, verified=len(verified), rejected=len(rejected),
          sources_ok=",".join(ok))
    return report


def _empty_report(kind: str, q: str, reason: str) -> dict:
    return {
        "ok": False, "kind": kind, "query": q, "policy": POLICY,
        "verified": [], "rejected": [],
        "summary": {"discovered": 0, "clusters": 0, "verified": 0, "rejected": 0,
                    "sources_ok": [], "sources_fail": [], "gate": "NO_VERIFIED_CLAIM"},
        "sources": [], "generated_at": _now(), "elapsed_ms": 0, "note": reason,
    }


def _unique_sources(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for e in items:
        for s in e.get("sources") or []:
            key = (s.get("name"), s.get("url"))
            if key not in seen:
                seen.add(key)
                out.append(s)
    return out[:40]


# ---------------------------------------------------------------- LLM（受控调用）

_DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"


def llm_available() -> bool:
    k = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    return bool(k) and not k.startswith("sk-your-key") and k != "sk-xxx"


_LLM_PROBE: dict = {"ts": 0.0, "available": None, "reason": ""}


def llm_probe(force: bool = False) -> dict:
    """真实探测大模型通道可用性（带 5 分钟缓存）。

    「配置了 Key」不等于「通道可用」：余额不足 / Key 失效时必须如实报告，
    否则前端会误以为可以产出译文或润色结果。
    """
    now = time.time()
    if (not force and _LLM_PROBE["available"] is not None
            and now - _LLM_PROBE["ts"] < 300):
        return dict(_LLM_PROBE)
    if not llm_available():
        out = {"ts": now, "available": False, "reason": "未配置 DEEPSEEK_API_KEY"}
    else:
        try:
            llm_complete("Reply with the single word OK.", "probe", temperature=0.0, timeout=12)
            out = {"ts": now, "available": True, "reason": "可用"}
        except Exception as e:
            out = {"ts": now, "available": False, "reason": redact(str(e))[:140]}
    _LLM_PROBE.update(out)
    return dict(_LLM_PROBE)


def llm_complete(system: str, user: str, temperature: float = 0.0, timeout: float = 30) -> str:
    """低温、无历史、隔离上下文的独立 LLM 调用；失败抛异常由调用方降级。"""
    key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if not llm_available():
        raise RuntimeError("LLM 未配置")
    payload = {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": fence("UNTRUSTED_USER_DATA", user)},
        ],
        "temperature": temperature,
        "max_tokens": 1200,
    }
    r = safe_post(_DEEPSEEK_URL, json_body=payload,
                  headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                  timeout=timeout)
    if r.status_code in (401, 402):
        raise RuntimeError("LLM 凭据无效或余额不足")
    r.raise_for_status()
    data = r.json()
    return strip_role_markers(data["choices"][0]["message"]["content"] or "").strip()


# ---------------------------------------------------------------- 翻译核验

_TERM_STD = "https://api.termonline.cn/main-serve/business/tm/tmWord/standardSearch"
_TERM_TIPS = "https://api.termonline.cn/main-serve/business/tm/tmWord/tips"
_TERM_HEADERS = {
    "Referer": "https://www.termonline.cn/",
    "Origin": "https://www.termonline.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def _term_items(payload: dict) -> list[dict]:
    std = ((payload or {}).get("result") or {}).get("standardVO") or {}
    out = []
    for w in std.get("tmWordList") or []:
        if not isinstance(w, dict):
            continue
        cn = clean_text(w.get("cnName") or "", 120)
        en = clean_text(w.get("enName") or "", 200)
        if not cn and not en:
            continue
        tid = str(w.get("id") or "").strip()
        out.append({
            "cn": cn, "en": en,
            "subject": clean_text(w.get("subjectName") or "", 80),
            "standard": clean_text(w.get("standardCode") or "", 80),
            "standard_name": clean_text(w.get("standardName") or "", 160),
            "code": clean_text(w.get("termCode") or "", 80),
            "url": f"https://www.termonline.cn/termDetail?id={tid}" if tid else "https://www.termonline.cn/",
        })
    return out


def extract_terms(text: str, limit: int = 6) -> list[str]:
    """从输入里抽取待核验的术语。

    旧实现用 `[\\u4e00-\\u9fff]{2,10}` 直接扫中文，会把「……基于注意力机制……」这类
    长串按 10 字硬切成「基于注」「意力机制」这种半词，导致术语库必然查不到、
    整段译文被连坐拒绝。这里改为：
      1) 短输入（≤30 字且无句读）整体视作一个术语；
      2) 长输入优先让模型抽词，且**只保留确实出现在原文里的片段**（杜绝模型臆造）；
      3) 模型不可用时，只取被标点/空白完整包围的 2~6 字中文串，绝不做跨词截断。
    """
    s = clean_text(text, 3000)
    # 只有「短且像术语」才整体视作术语；12 字以内是中文术语的常见上限，
    # 放得太宽（原来 30）会把整句当成术语，导致术语库必然查不到。
    if len(s) <= 12 and not re.search(r"[。！？.!?；;，,]", s):
        return [s]

    cands: list[str] = []
    try:
        if llm_available():
            raw = llm_complete(
                "Extract up to 5 domain-specific technical terms that appear literally in the "
                "fenced DATA. Output one term per line, no numbering, no punctuation, no notes.",
                s,
                temperature=0.0,
                timeout=15,
            )
            for line in (raw or "").splitlines():
                t = line.strip().strip("-*•· \t").strip()
                if not (2 <= len(t) <= 40 and t in s):
                    continue
                # 术语不能是整句：中文术语一般不超过 12 字，且不应含句读
                if re.search(r"[，。！？；,.!?;]", t):
                    continue
                if re.search(r"[\u4e00-\u9fff]", t) and len(re.sub(r"\s", "", t)) > 12:
                    continue
                cands.append(t)
    except Exception:
        pass

    if not cands:
        for clause in re.split(r"[，。！？；、,.!?;\s（）()\[\]【】「」“”\"'/]+", s):
            for run in re.findall(r"[\u4e00-\u9fff]+", clause):
                if 2 <= len(run) <= 6:
                    cands.append(run)
        cands += re.findall(r"\b[A-Za-z][A-Za-z\-]{2,24}(?:\s+[A-Za-z][A-Za-z\-]{2,24}){0,2}\b", s)

    seen, out = set(), []
    for t in cands:
        k = norm_text(t)
        if k and k not in seen and len(k) >= 2:
            seen.add(k)
            out.append(t.strip())
        if len(out) >= limit:
            break
    return out


def _verify_term(term: str) -> dict:
    """单个术语：正向国标查询 → 用所得译名反向独立复核 → 一致才通过。"""
    checks = []
    # 通道 A：全国科学技术名词审定委员会，审定译名（权威、可溯源）
    try:
        data = safe_json(_TERM_STD, params={"term": term, "match": 1, "pageNo": 1, "pageSize": 5},
                         headers=_TERM_HEADERS, timeout=12)
        items = _term_items(data)
        checks.append({
            "channel": "术语在线 · 国标审定译名", "endpoint": _TERM_STD,
            "verdict": "agree" if items else "unavailable",
            "detail": f"返回 {len(items)} 条审定记录" if items else "未检出审定译名",
            "checked_at": _now(),
        })
    except Exception as e:
        items = []
        checks.append({"channel": "术语在线 · 国标审定译名", "endpoint": _TERM_STD,
                       "verdict": "unavailable", "detail": f"通道不可用：{e.__class__.__name__}",
                       "checked_at": _now()})

    # 通道 B：反向独立复核 —— 用得到的英文译名反查，看是否回到原中文术语
    reverse_ok = False
    candidates = [i for i in items if i["en"] and i["cn"]]
    if candidates:
        target = candidates[0]
        try:
            back = safe_json(_TERM_STD, params={"term": target["en"], "match": 1,
                                               "pageNo": 1, "pageSize": 5},
                             headers=_TERM_HEADERS, timeout=12)
            back_items = _term_items(back)
            reverse_ok = any(similarity(b["cn"], target["cn"]) >= 0.85 for b in back_items)
            checks.append({
                "channel": "译名反向独立复核", "endpoint": _TERM_STD,
                "verdict": "agree" if reverse_ok else "conflict",
                "detail": (f"以「{target['en']}」反查，回到「{target['cn']}」" if reverse_ok
                           else f"以「{target['en']}」反查未回到原术语"),
                "checked_at": _now(),
            })
        except Exception as e:
            checks.append({"channel": "译名反向独立复核", "endpoint": _TERM_STD,
                           "verdict": "unavailable", "detail": f"通道不可用：{e.__class__.__name__}",
                           "checked_at": _now()})
    else:
        checks.append({"channel": "译名反向独立复核", "endpoint": _TERM_STD,
                       "verdict": "unavailable", "detail": "无可反查的审定译名", "checked_at": _now()})

    agree = [c for c in checks if c["verdict"] == "agree"]
    conflict = [c for c in checks if c["verdict"] == "conflict"]
    verdict = "verified" if len(agree) >= CHECKS_REQUIRED and not conflict else (
        "disputed" if conflict else "unverifiable")
    top = candidates[0] if candidates else {}
    return {
        "id": "T" + hashlib.sha1(norm_text(term).encode()).hexdigest()[:8],
        "kind": "translation",
        "claim": term,
        "fields": {
            "source_term": term,
            "standard_cn": top.get("cn", ""), "standard_en": top.get("en", ""),
            "subject": top.get("subject", ""), "standard_code": top.get("standard", ""),
            "standard_name": top.get("standard_name", ""), "term_code": top.get("code", ""),
            "url": top.get("url", ""),
            "alternatives": [{"cn": i["cn"], "en": i["en"]} for i in candidates[1:4]],
        },
        "sources": [
            source_ref("术语在线 · 全国科学技术名词审定委员会", top.get("url", ""),
                       endpoint=_TERM_STD,
                       identifier=top.get("standard") or top.get("code") or "",
                       note=f"审定标准：{top.get('standard_name','')}")
        ] if top else [],
        "checks": checks,
        "agreement": f"{len(agree)}/{len(checks)}",
        "agreement_required": CHECKS_REQUIRED,
        "verdict": verdict,
        "confidence": min(1.0, round(0.68 + 0.12 * len(agree)
                                     + (0.10 if top.get("standard") else 0), 3))
                      if verdict == "verified" else 0.0,
        "reject_reason": "" if verdict == "verified" else
                         (conflict[0]["detail"] if conflict else f"仅 {len(agree)} 条通道确认，未达 {CHECKS_REQUIRED} 条"),
    }


def _split_segments(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？；.!?])\s*|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


def _translate_twice(text: str, target: str) -> tuple[list[str], list[str], bool]:
    """两次彼此独立、无共享上下文的低温翻译，返回 (A译文分句, B译文分句, 是否可用)。

    关键点：两条通道执行的是**同一个任务**，独立性来自「分开调用、不共享上下文」，
    而不是「用不同口径」。若让 A 走学术意译、B 走保守直译，两者天然不同，
    再要求 90% 相似度必然全部判为冲突，严谨性就退化成了「永远不给结果」。

    - 通道 A：逐句单独翻译（句与句之间没有上下文）
    - 通道 B：整篇一次性翻译后切分
    同一任务下的两次独立运行，若结果一致，才说明输出稳定、可复现。
    """
    segs = _split_segments(text)[:8]
    sys_prompt = (
        "You are a scientific translation engine. Translate the fenced DATA into "
        f"{target} using standard academic terminology. "
        "Output ONLY the translation, no notes, no markdown, no explanations."
    )

    # 通道 A：逐句独立翻译
    a: list[str] = []
    try:
        for seg in segs:
            out = clean_text(
                llm_complete(sys_prompt + " Translate exactly one sentence.", seg, temperature=0.0),
                2000,
            )
            if not out:
                raise RuntimeError("empty")
            a.append(out)
    except Exception:
        a = []

    # 通道 B：整篇一次性翻译，再切分
    b: list[str] = []
    try:
        whole = clean_text(llm_complete(sys_prompt, text, temperature=0.0), 6000)
        b = _split_segments(whole)[:len(segs)] if segs else []
    except Exception:
        b = []

    if not a or not b:
        return [], [], False
    return a, b, True


def _back_translation_check(original: list[str], translated: list[str]) -> dict:
    """回译复核：把一致译文译回原语言，与原文比对。"""
    try:
        sys_prompt = ("Translate the fenced DATA back into the source language (Chinese if the "
                      "original was Chinese, otherwise English). Output ONLY the translation.")
        back = clean_text(llm_complete(sys_prompt, " ".join(translated), temperature=0.0), 6000)
        score = similarity(" ".join(original), back)
        return {"verdict": "agree" if score >= 0.45 else "conflict",
                "detail": f"回译相似度 {score}", "similarity": score,
                "channel": "独立回译一致性", "checked_at": _now()}
    except Exception as e:
        return {"verdict": "unavailable", "detail": f"回译通道不可用：{e.__class__.__name__}",
                "channel": "独立回译一致性", "checked_at": _now()}


def verify_translation(text: str, target: str = "英语") -> dict:
    """翻译核验：术语走国标双向复核；整句走两次独立翻译 + 回译，逐句门控。"""
    t0 = time.time()
    src = clean_text(text, 3000)
    if not src:
        return _empty_report("translation", src, "待译文本为空")

    terms = extract_terms(src)
    term_items = [_verify_term(t) for t in terms] if terms else []
    term_verified = [x for x in term_items if x["verdict"] == "verified"]
    # 标注通道：同一段文本会同时走「术语级」与「整句级」两条独立门控，
    # 不标注会让拒绝公示看起来像重复条目，也会让精确度的统计口径含糊。
    term_rejected = []
    for x in term_items:
        if x["verdict"] != "verified":
            y = dict(x)
            y["claim"] = "术语级 · " + str(x.get("claim") or x.get("fields", {}).get("original") or "条目")
            term_rejected.append(y)

    segs = _split_segments(src)
    a, b, llm_ok = _translate_twice(src, target)
    sentence_items = []
    if llm_ok:
        n = min(len(segs), len(a), len(b))
        back = _back_translation_check(segs[:n], a[:n]) if (BACKTRANSLATION and n) else {
            "verdict": "unavailable", "detail": "回译复核已关闭", "channel": "独立回译一致性"}
        for i in range(n):
            sim = similarity(a[i], b[i])
            agree = sim >= 0.90
            # 回译只作「严重偏离」时的否决通道：Jaccard 对同义改写本身就很敏感，
            # 若只要回译不完全一致就否决，等于把正确的同义译法一并枪毙。
            back_score = float(back.get("similarity") or 0.0)
            if agree and back.get("verdict") == "conflict" and back_score < 0.25:
                agree = False
            checks = [
                {"channel": "独立翻译 A（学术译法）", "verdict": "agree" if agree else "conflict",
                 "detail": a[i][:200], "checked_at": _now()},
                {"channel": "独立翻译 B（保守直译）", "verdict": "agree" if agree else "conflict",
                 "detail": b[i][:200], "checked_at": _now(),
                 "title_similarity": sim},
                dict(back),
            ]
            n_agree = sum(1 for c in checks if c["verdict"] == "agree")
            verdict = "verified" if agree and n_agree >= CHECKS_REQUIRED else (
                "disputed" if not agree else "unverifiable")
            sentence_items.append({
                "id": "S" + hashlib.sha1((segs[i] + a[i]).encode()).hexdigest()[:8],
                "kind": "translation", "claim": segs[i],
                "fields": {"original": segs[i], "translation_a": a[i], "translation_b": b[i],
                           "final": a[i] if verdict == "verified" else "",
                           "target": target},
                "sources": [source_ref("双次独立翻译 + 回译", "",
                                       endpoint=_DEEPSEEK_URL, note="低温、隔离上下文、无共享历史")],
                "checks": checks,
                "agreement": f"{n_agree}/{len(checks)}",
                "agreement_required": CHECKS_REQUIRED,
                "verdict": verdict,
                "confidence": round(min(1.0, 0.55 + 0.15 * n_agree + 0.2 * sim), 3)
                              if verdict == "verified" else 0.0,
                "reject_reason": "" if verdict == "verified" else
                                 (f"两次独立译文不一致（相似度 {sim}）" if not agree
                                  else f"仅 {n_agree} 条通道确认"),
            })
    # LLM 不可用时绝不编造译文，明确标注
    if not llm_ok:
        sentence_items.append({
            "id": "S-unavailable", "kind": "translation", "claim": "整句级 · " + src[:120],
            "fields": {"original": src[:400], "final": "", "target": target,
                       "note": "未配置大模型凭据；为避免编造，不输出任何整句译文"},
            "sources": [], "checks": [{"channel": "独立翻译 A/B", "verdict": "unavailable",
                                       "detail": "LLM 不可用", "checked_at": _now()}],
            "agreement": "0/2", "verdict": "unverifiable", "confidence": 0.0,
            "reject_reason": "缺少可用的独立翻译通道，按严谨策略不生成译文",
        })

    all_items = term_verified + [x for x in sentence_items if x["verdict"] == "verified"]
    rejected = term_rejected + [x for x in sentence_items if x["verdict"] != "verified"]
    report = {
        "ok": True, "kind": "translation", "query": src[:200], "target": target,
        "policy": POLICY, "verified": all_items, "rejected": rejected,
        "terms": {"checked": len(term_items), "verified": len(term_verified)},
        "sentences": {"checked": len(sentence_items),
                      "verified": sum(1 for x in sentence_items if x["verdict"] == "verified")},
        "summary": {
            "discovered": len(term_items) + len(sentence_items),
            "clusters": len(all_items) + len(rejected),
            "verified": len(all_items), "rejected": len(rejected),
            "sources_ok": ["术语在线"] if any(
                c.get("verdict") != "unavailable"
                for x in term_items for c in x.get("checks", [])) else [],
            "sources_fail": [], "checks_required": CHECKS_REQUIRED,
            "gate": "PASS" if all_items else "NO_VERIFIED_CLAIM",
        },
        "sources": _unique_sources(all_items + rejected),
        "generated_at": _now(),
        "elapsed_ms": int((time.time() - t0) * 1000),
    }
    audit("verify.translation", user_input=src, verified=len(all_items), rejected=len(rejected))
    return report


# ---------------------------------------------------------------- 引用真伪核验

def _reg_crossref(doi: str) -> dict:
    """注册机构 1：Crossref DOI 精确记录。"""
    url = f"https://api.crossref.org/works/{quote(doi, safe='/.-_')}"
    try:
        r = safe_get(url, headers={"User-Agent": "ZhihuiYantu-Rigor/2.0 (mailto:local@localhost)"})
        if r.status_code == 404:
            return {"found": False, "check": _check_result("Crossref DOI 注册记录", url, "unavailable",
                                                           "该 DOI 不在 Crossref 注册（可能由 DataCite 注册）", url=url)}
        r.raise_for_status()
        msg = r.json().get("message") or {}
        year = ""
        for k in ("published-print", "published-online", "issued"):
            p = (msg.get(k) or {}).get("date-parts")
            if p and p[0] and p[0][0]:
                year = str(p[0][0]); break
        return {"found": True, "title": (msg.get("title") or [""])[0], "year": year,
                "url": url, "name": "Crossref DOI 注册记录"}
    except Exception as e:
        return {"found": False, "check": _check_result("Crossref DOI 注册记录", url, "unavailable",
                                                       f"通道不可用：{e.__class__.__name__}", url=url)}


def _reg_datacite(doi: str) -> dict:
    """注册机构 2：DataCite（arXiv / Zenodo / 数据集 DOI 的注册机构，Crossref 查不到）。"""
    url = f"https://api.datacite.org/dois/{quote(doi, safe='/.-_')}"
    try:
        r = safe_get(url)
        if r.status_code == 404:
            return {"found": False, "check": _check_result("DataCite DOI 注册记录", url, "unavailable",
                                                           "该 DOI 不在 DataCite 注册", url=url)}
        r.raise_for_status()
        attr = ((r.json().get("data") or {}).get("attributes") or {})
        titles = attr.get("titles") or []
        return {"found": True, "title": (titles[0].get("title") if titles else "") or "",
                "year": str(attr.get("publicationYear") or ""), "url": url,
                "name": "DataCite DOI 注册记录"}
    except Exception as e:
        return {"found": False, "check": _check_result("DataCite DOI 注册记录", url, "unavailable",
                                                       f"通道不可用：{e.__class__.__name__}", url=url)}


def _idx_openalex(doi: str) -> dict:
    """独立索引 3：OpenAlex 按 DOI 反查。"""
    url = "https://api.openalex.org/works"
    try:
        data = safe_json(url, params={"filter": f"doi:{doi}", "per-page": 1})
        rs = data.get("results") or []
        if not rs:
            return {"found": False, "check": _check_result("OpenAlex DOI 精确反查", url, "unavailable",
                                                           "OpenAlex 未收录该 DOI（索引未覆盖 ≠ 不存在）", url=url)}
        it = rs[0]
        return {"found": True, "title": it.get("title") or "",
                "year": str(it.get("publication_year") or ""), "url": it.get("doi") or url,
                "name": "OpenAlex DOI 精确反查"}
    except Exception as e:
        return {"found": False, "check": _check_result("OpenAlex DOI 精确反查", url, "unavailable",
                                                       f"通道不可用：{e.__class__.__name__}", url=url)}


def _idx_europepmc(doi: str) -> dict:
    """独立索引 4：Europe PMC 按 DOI 字段检索（生物医学覆盖强）。"""
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    try:
        data = safe_json(url, params={"query": f'DOI:"{doi}"', "format": "json", "pageSize": 1})
        rs = (data.get("resultList") or {}).get("result", [])
        if not rs:
            return {"found": False, "check": _check_result("Europe PMC DOI 精确检索", url, "unavailable",
                                                           "Europe PMC 未收录该 DOI（学科范围外属正常）", url=url)}
        it = rs[0]
        return {"found": True, "title": it.get("title") or "",
                "year": str(it.get("pubYear") or ""), "url": url,
                "name": "Europe PMC DOI 精确检索"}
    except Exception as e:
        return {"found": False, "check": _check_result("Europe PMC DOI 精确检索", url, "unavailable",
                                                       f"通道不可用：{e.__class__.__name__}", url=url)}


def _verify_doi_existence(doi: str, hint_title: str = "", hint_year: str = "") -> dict:
    """DOI 真伪核验：多家注册机构 + 独立索引并行确认。

    关键精确度规则：**「某家索引没收录」只记 unavailable，不判 conflict**，
    因为 Crossref / DataCite 是互补的注册机构，OpenAlex / Europe PMC 各有学科覆盖边界。
    只有「查到了但字段对不上」才是真冲突。伪造 DOI 则是所有通道都 unavailable → 复核不足 → 剔除。
    """
    fetchers = [_reg_crossref, _reg_datacite, _idx_openalex, _idx_europepmc]
    raw = []
    ex = ThreadPoolExecutor(max_workers=len(fetchers))
    futs = [ex.submit(fn, doi) for fn in fetchers]
    try:
        for f in as_completed(futs, timeout=DEADLINE):
            try:
                raw.append(f.result())
            except Exception as e:
                raw.append({"found": False, "check": _check_result("未知通道", "", "unavailable",
                                                                    f"异常：{e.__class__.__name__}")})
    except Exception:
        pass
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    found = [x for x in raw if x.get("found")]
    checks = [x["check"] for x in raw if not x.get("found")]
    conflicts = []
    # 用查到的第一条记录作为基准，其余逐条比对（标题 + 年份）
    base = found[0] if found else None
    if base:
        for x in found:
            sim = similarity(base["title"], x["title"]) if (base["title"] and x["title"]) else 1.0
            y1, y2 = str(base.get("year") or "")[:4], str(x.get("year") or "")[:4]
            bad = (sim < TITLE_THRESHOLD) or (bool(y1 and y2 and y1 != y2))
            checks.append(_check_result(
                x["name"], x.get("url", ""),
                "conflict" if bad else "agree",
                (f"记录不一致：标题相似度 {sim}；年份 {y1 or '—'}/{y2 or '—'}"
                 if bad else f"「{clean_text(x['title'], 90)}」· {y1 or y2 or '年份未标注'} · 与基准一致"),
                sim, y2, x.get("url", "")))
            if bad:
                conflicts.append(x["name"])
    # 用户给的标题/年份也能作为一条独立校验
    if hint_title and base and base["title"]:
        sim = similarity(hint_title, base["title"])
        if sim >= 0.60:
            checks.append(_check_result("引用串标题比对", "", "agree",
                                        f"与注册记录标题相似度 {sim}", sim))
        # 相似度低不判冲突：引用串常含作者、期刊等噪声
    if hint_year and base and base.get("year"):
        if str(hint_year)[:4] == str(base["year"])[:4]:
            checks.append(_check_result("引用串年份比对", "", "agree", f"年份 {hint_year[:4]} 一致"))
        else:
            checks.append(_check_result("引用串年份比对", "", "conflict",
                                        f"引用串 {hint_year[:4]} / 注册记录 {base['year'][:4]} 不一致"))
            conflicts.append("引用串年份")

    agree = [c for c in checks if c["verdict"] == "agree"]
    conflict = [c for c in checks if c["verdict"] == "conflict"]
    if conflict:
        verdict, reason = "disputed", "；".join(c["detail"] for c in conflict)[:300]
    elif len(agree) >= CHECKS_REQUIRED:
        verdict, reason = "verified", ""
    else:
        verdict = "unverifiable"
        reason = (f"仅 {len(agree)}/{CHECKS_REQUIRED} 条通道确认存在；"
                  "所有注册机构与索引均未查到该 DOI，不能认定为真实文献")

    return {
        "verdict": verdict, "reason": reason, "checks": checks,
        "agreement": f"{len(agree)}/{len(checks)}",
        "agreement_required": CHECKS_REQUIRED,
        "canonical_title": base["title"] if base else "",
        "canonical_year": base.get("year", "") if base else "",
        "confidence": round(min(1.0, 0.5 + 0.12 * len(agree) + 0.1 * len(found)), 3)
                      if verdict == "verified" else 0.0,
        "found_in": [x["name"] for x in found],
    }


def verify_citation_strict(citation: str) -> dict:
    """引用核验：抽 DOI → 多注册机构 + 独立索引并行确认；无 DOI 则按标题多源复核。"""
    t0 = time.time()
    c = clean_text(citation, 600)
    m = re.search(r"10\.\d{4,9}/[^\s,;\"'\]\)]+", c)
    doi = norm_doi(m.group(0)) if m else ""
    if doi:
        hint_title = re.sub(r"10\.\d{4,9}/\S+", "", c).strip(" .,;:") or ""
        ym = re.search(r"\b(19|20)\d{2}\b", c)
        hint_year = ym.group(0) if ym else ""
        v = _verify_doi_existence(doi, hint_title, hint_year)
        item = {
            "id": "C" + hashlib.sha1(doi.encode()).hexdigest()[:8],
            "kind": "citation", "claim": doi,
            "fields": {"doi": doi, "url": f"https://doi.org/{doi}",
                       "title": v["canonical_title"], "year": v["canonical_year"],
                       "found_in": v["found_in"]},
            "sources": [
                source_ref(name, f"https://doi.org/{doi}", identifier=doi,
                           note="DOI 精确记录（注册机构 / 独立索引）")
                for name in v["found_in"]
            ],
            "checks": v["checks"], "verdict": v["verdict"],
            "agreement": v["agreement"], "confidence": v["confidence"],
            "reject_reason": v["reason"],
        }
        return {
            "ok": True, "kind": "citation", "query": c, "doi": doi,
            "policy": POLICY,
            "verified": [item] if v["verdict"] == "verified" else [],
            "rejected": [] if v["verdict"] == "verified" else [item],
            "summary": {"gate": "PASS" if v["verdict"] == "verified" else "NO_VERIFIED_CLAIM",
                        "verified": 1 if v["verdict"] == "verified" else 0,
                        "rejected": 0 if v["verdict"] == "verified" else 1,
                        "checks_required": CHECKS_REQUIRED, "found_in": v["found_in"]},
            "sources": _unique_sources([item]),
            "generated_at": _now(), "elapsed_ms": int((time.time() - t0) * 1000),
        }
    # 无 DOI：走标准文献核验流程
    rep = verify_literature(c[:180], per_source=3)
    rep["kind"] = "citation"
    rep["note"] = "引用串中未检出 DOI，已按标题走多源独立复核"
    return rep
