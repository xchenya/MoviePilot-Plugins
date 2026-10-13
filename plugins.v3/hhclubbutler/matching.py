# -*- coding: utf-8 -*-
"""Read-only association between HH rescue eligibility and downloader torrents.

The HH completed-rescue page is the authoritative inventory.  A downloader is
only an optional annotation; missing/ambiguous matches must never discard an
eligible site row or grant permission to delete files.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from difflib import SequenceMatcher
import re
import unicodedata
from typing import Any


_GENERIC = frozenset({
    "web", "dl", "webrip", "webdl", "bluray", "bdrip", "hdrip",
    "h264", "h265", "h266", "x264", "x265", "hevc", "avc", "av1",
    "1080p", "2160p", "720p", "480p", "hdr", "dv", "atmos",
    "ddp", "aac", "dts", "truehd", "dd", "nf",
})
_SITE_TRACKERS = ("hhanclub", "hhancclub", "hhclub", "hanclub")


def normalize_name(value: Any) -> str:
    """Normalize punctuation and fullwidth text, retaining Unicode letters."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(ch for ch in text if ch.isalnum())


def _tokens(value: Any) -> set[str]:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return {t for t in re.findall(r"[^\W_]+", text)
            if len(t) >= 3 and t not in _GENERIC}


def _size_compatible(site: dict, torrent: dict) -> bool | None:
    """None = size unavailable, False = clear contradiction."""
    try:
        a = float(site.get("size") or 0)
        b = float(torrent.get("size_gb") or 0)
    except (ValueError, TypeError):
        return None
    if a <= 0 or b <= 0:
        return None
    return abs(a - b) <= max(0.18, 0.06 * a)



_TRANSLATED_NAME_RE = re.compile(
    r"^\s*(?P<cn>[\u3400-\u9fff]{2,}(?:[\u3400-\u9fff ]{0,24}))"
    r"[.\-_·|\s]+(?P<release>[A-Za-z].+)$",
    re.I,
)
_RELEASE_MARKER_RE = re.compile(
    r"\b(?:19\d{2}|20\d{2}|s\d{1,3}|e\d{1,3}|\d{3,4}p)\b",
    re.I,
)


def translated_release_key(value: Any) -> str | None:
    """Return the English release suffix ONLY for a leading Chinese-title alias.

    Example: 上古情歌.A.Lifetime.Love.S01.2017... -> alifetimeloves012017...
    No translation dictionaries or fuzzy stripping of arbitrary Han characters.
    """
    original = unicodedata.normalize("NFKC", str(value or "")).strip()
    match = _TRANSLATED_NAME_RE.fullmatch(original)
    if not match:
        return None
    release = match.group("release").strip()
    normalized = normalize_name(release)
    # Short English fragments must never become release aliases.
    if len(normalized) < 24 or not _RELEASE_MARKER_RE.search(release):
        return None
    return normalized


def translated_size_matches(site: dict, torrent: dict) -> bool:
    """Require independent positive size evidence for translation alias linking."""
    try:
        site_gb = float(site.get("size") or 0)
        torrent_gb = float(torrent.get("size_gb") or 0)
    except (TypeError, ValueError):
        return False
    if site_gb <= 0 or torrent_gb <= 0:
        return False
    return abs(site_gb - torrent_gb) <= max(0.05, site_gb * 0.015)


def _candidate_indices(
    site: dict, prefix: dict[str, list[int]], token_idx: dict[str, list[int]],
    token_frequencies: Counter,
) -> set[int]:
    name = normalize_name(site.get("title"))
    hits = set(prefix.get(name[:12], [])) if len(name) >= 12 else set()
    tokens = sorted(_tokens(site.get("title")), key=lambda t: token_frequencies[t])
    for token in tokens[:5]:
        candidates = token_idx.get(token, ())
        # A common token such as "movie" is not enough for an exhaustive scan.
        if len(candidates) <= 70:
            hits.update(candidates)
        if len(hits) > 150:
            return set()  # refuse ambiguous fuzzy matches
    return hits


def _match_record(
    site: dict, torrent: dict, name: str, canon: str, allow_exact: bool
) -> tuple[str, float] | None:
    target = normalize_name(torrent.get("name"))
    if not target or not canon or not name:
        return None
    size = _size_compatible(site, torrent)
    if allow_exact and canon == target:
        # Equal canonical titles are strong evidence, even if size was not
        # reported by a downloader. Strong size contradictions are unsafe.
        return ("exact", 1.0) if size is not False else None
    if not (len(canon) >= 16 and len(target) >= 16):
        return None
    ratio_length = min(len(canon), len(target)) / max(len(canon), len(target))
    if ratio_length < 0.72:
        return None
    ratio = SequenceMatcher(None, canon, target, autojunk=False).ratio()
    # A significantly different torrent title cannot be rescued by similar
    # size alone.  A missing size requires an almost identical long title.
    if size is False or ratio < (0.91 if size is True else 0.965):
        return None
    return ("similar", ratio)


def associate_rescue_seeds(
    site_seeds: list[dict[str, Any]],
    downloader_torrents: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Preserve site inventory and resolve downloader ownership safely.

    Exact canonical title matches have precedence over fuzzy matches. A
    downloader task used by an exact match is never borrowed as a fuzzy
    candidate for another site row. Repeated copies of the SAME downloader
    hash are collapsed, but distinct hashes/downloaders stay distinct.
    """
    # Some downloader helpers may return repeated representations of the same
    # torrent. They are not separate deletion targets; do not manufacture
    # ambiguity from identical (downloader, hash, name) records.
    torrents: list[dict[str, Any]] = []
    seen_tasks: set[tuple[str, str, str]] = set()
    duplicates_ignored = 0
    for raw in downloader_torrents:
        label = str(raw.get("downloader") or "").strip()
        name_key = normalize_name(raw.get("name"))
        info_hash = str(raw.get("hash") or "").strip().lower()
        key = (label.casefold(), info_hash, name_key)
        if label and info_hash and name_key and key in seen_tasks:
            duplicates_ignored += 1
            continue
        if label and info_hash and name_key:
            seen_tasks.add(key)
        torrents.append(raw)

    by_exact: dict[str, list[int]] = defaultdict(list)
    by_translated: dict[str, list[int]] = defaultdict(list)
    by_prefix: dict[str, list[int]] = defaultdict(list)
    by_token: dict[str, list[int]] = defaultdict(list)
    counts: Counter = Counter()
    site_names = Counter(normalize_name(x.get("title")) for x in site_seeds)

    for index, torrent in enumerate(torrents):
        canon = normalize_name(torrent.get("name"))
        if not canon:
            continue
        by_exact[canon].append(index)
        english_alias = translated_release_key(torrent.get("name"))
        if english_alias:
            by_translated[english_alias].append(index)
        if len(canon) >= 12:
            by_prefix[canon[:12]].append(index)
        for token in _tokens(torrent.get("name")):
            by_token[token].append(index)
            counts[token] += 1

    # First pass: reserve exact downloader tasks, regardless of whether the
    # eventual site row is itself ambiguous (e.g. duplicate site titles).
    exact_groups: list[list[tuple[int, str, float]]] = []
    exact_reserved: set[int] = set()
    exact_site_owners: Counter = Counter()
    for site in site_seeds:
        canon = normalize_name(site.get("title"))
        original = str(site.get("title") or "")
        group: list[tuple[int, str, float]] = []
        for index in by_exact.get(canon, ()):
            hit = _match_record(site, torrents[index], original, canon, True)
            if hit:
                group.append((index, "exact", hit[1]))
                exact_reserved.add(index)
                exact_site_owners[index] += 1
        exact_groups.append(group)

    # Intermediate priority: a known Chinese title prefix can be discarded
    # ONLY when the remaining complete English release name equals the site
    # release AND independently reported sizes agree closely. Keep this
    # separate from generic fuzzy matches and do not authorize deletion.
    translated_reserved: set[int] = set()
    translated_site_owners: Counter = Counter()
    strong_groups: list[list[tuple[int, str, float]]] = []
    translated_alias_count = 0
    for site, exact_group in zip(site_seeds, exact_groups):
        canon = normalize_name(site.get("title"))
        aliases = []
        for index in by_translated.get(canon, ()):
            if index in exact_reserved:
                continue
            if translated_size_matches(site, torrents[index]):
                aliases.append((index, "translated", 1.0))
                translated_reserved.add(index)
                translated_site_owners[index] += 1
                translated_alias_count += 1
        # Multiple real tasks with exact/suffix identities for one site entry
        # are a genuine conflict, even if in different downloaders.
        strong_groups.append(list(exact_group) + aliases)

    # Last priority: fuzzy suggestions only use unclaimed tasks. Otherwise
    # one translated alias could be shared by several vaguely similar rows.
    strong_reserved = exact_reserved | translated_reserved
    matches: list[list[tuple[int, str, float]]] = []
    fuzzy_shared: Counter = Counter()
    fuzzy_skipped_reserved = 0
    for site, strong_group in zip(site_seeds, strong_groups):
        if strong_group:
            matches.append(strong_group)
            continue
        canon = normalize_name(site.get("title"))
        original = str(site.get("title") or "")
        candidates = _candidate_indices(site, by_prefix, by_token, counts)
        scored = []
        for index in candidates:
            if index in strong_reserved:
                fuzzy_skipped_reserved += 1
                continue
            hit = _match_record(site, torrents[index], original, canon, False)
            if hit:
                scored.append((index, hit[0], hit[1]))
        selected = []
        if scored:
            scored.sort(key=lambda x: x[2], reverse=True)
            top = scored[0][2]
            selected = [hit for hit in scored if hit[2] >= top - 0.035]
        matches.append(selected)
        fuzzy_shared.update(index for index, _, _ in selected)

    entries: list[dict[str, Any]] = []
    stats = {
        "eligible": len(site_seeds), "linked": 0, "exact": 0,
        "translated": 0, "similar": 0, "ambiguous": 0, "unmatched": 0,
        "deletable": 0,
        "ambiguity_multiple_tasks": 0,
        "ambiguity_duplicate_site_titles": 0,
        "ambiguity_shared_fuzzy": 0,
        "duplicate_downloader_rows_ignored": duplicates_ignored,
        "fuzzy_exact_claims_blocked": fuzzy_skipped_reserved,
        "translation_suffix_claims": translated_alias_count,
    }
    for site, group in zip(site_seeds, matches):
        item = dict(site)
        # An unlinked site record remains part of the full eligible inventory.
        item.update({
            "downloader": "", "downloaders": [], "hash": "",
            "match_status": "unmatched", "match_reason": "下载器中暂未匹配",
            "can_delete": False, "matched": False,
        })
        entries.append(item)
        if not group:
            stats["unmatched"] += 1
            continue

        unique = {
            str(torrents[index].get("downloader") or "").strip()
            for index, _, _ in group
        }
        item["downloaders"] = sorted(x for x in unique if x)
        item["downloader"] = " / ".join(item["downloaders"])
        item["matched"] = True
        stats["linked"] += 1

        norm = normalize_name(item.get("title"))
        if site_names[norm] > 1:
            item["match_status"] = "ambiguous"
            item["match_reason"] = "站点存在不同种子ID但名称相同，无法确定删除对象"
            stats["ambiguous"] += 1
            stats["ambiguity_duplicate_site_titles"] += 1
            continue
        if len(group) > 1:
            item["match_status"] = "ambiguous"
            item["match_reason"] = (
                "多个下载器中存在同名任务，无法自动选择删除目标"
                if len(item["downloaders"]) > 1
                else "同一下载器有多个不同哈希的同名任务，需人工核对"
            )
            stats["ambiguous"] += 1
            stats["ambiguity_multiple_tasks"] += 1
            continue

        index, match_type, _ = group[0]
        if (match_type in {"exact", "translated"}
                and (exact_site_owners[index] + translated_site_owners[index]) > 1):
            item["match_status"] = "ambiguous"
            item["match_reason"] = "同一下载任务被多个站点条目强匹配命中"
            stats["ambiguous"] += 1
            stats["ambiguity_duplicate_site_titles"] += 1
            continue
        if (match_type == "similar" and fuzzy_shared[index] > 1):
            item["match_status"] = "ambiguous"
            item["match_reason"] = "多个站点条目近似匹配同一下载任务，未能唯一关联"
            stats["ambiguous"] += 1
            stats["ambiguity_shared_fuzzy"] += 1
            continue

        torrent = torrents[index]
        item["match_status"] = match_type
        stats[match_type] += 1
        for field in (
            "upspeed", "dlspeed", "eta", "ratio", "path",
            "cur_seeders", "cur_leechers", "tracker", "added", "progress"
        ):
            if torrent.get(field) is not None:
                item[field] = torrent[field]

        tracker_ok = bool(torrent.get("site_tracker"))
        progress = torrent.get("progress")
        state = str(torrent.get("state") or "").strip().lower()
        completed_states = {
            "seeding", "seed_pending", "stalledup", "uploading",
            "pausedup", "queuedup", "forcedup",
        }
        complete = (progress >= 0.999 if progress is not None
                    else state in completed_states)
        if not complete:
            item["match_status"] = "downloading" if progress is not None else "unverified"
            item["match_reason"] = ("下载任务尚未完成" if progress is not None
                                    else "下载进度未确认，禁止删除")
        elif not tracker_ok:
            item["match_status"] = "unverified"
            item["match_reason"] = "Tracker 未确认是憨憨站，仅供查看"
        elif match_type == "translated":
            item["match_reason"] = (
                "中文译名前缀 + 完整英文发布名 + 文件大小匹配；"
                "已关联，名称不完全相同，禁止直接删除文件"
            )
        elif match_type == "similar":
            item["match_reason"] = "名称近似匹配，仅供查看，不允许直接删除"
        else:
            item["match_reason"] = "名称精确匹配且已确认憨憨站 Tracker"

        if (match_type == "exact" and tracker_ok and complete
                and torrent.get("hash") and item["downloader"]):
            item["hash"] = str(torrent["hash"])
            item["can_delete"] = True
            stats["deletable"] += 1
    return entries, stats
