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
    """Retain ALL site rows; annotate unique trustworthy downloader associations.

    Complexity is near-linear for exact matches.  A token/prefix inverted index
    limits bounded fuzzy comparisons; no quadratic full-catalog scan is used.
    """
    by_exact: dict[str, list[int]] = defaultdict(list)
    by_prefix: dict[str, list[int]] = defaultdict(list)
    by_token: dict[str, list[int]] = defaultdict(list)
    counts: Counter = Counter()
    site_names = Counter(normalize_name(x.get("title")) for x in site_seeds)

    for index, torrent in enumerate(downloader_torrents):
        canon = normalize_name(torrent.get("name"))
        if not canon:
            continue
        by_exact[canon].append(index)
        if len(canon) >= 12:
            by_prefix[canon[:12]].append(index)
        ts = _tokens(torrent.get("name"))
        for token in ts:
            by_token[token].append(index)
            counts[token] += 1

    entries: list[dict[str, Any]] = []
    matches: list[list[tuple[int, str, float]]] = []
    for site in site_seeds:
        item = dict(site)
        # Site identity and eligibility do not depend on the downloader.
        item.update({
            "downloader": "", "downloaders": [], "hash": "",
            "match_status": "unmatched", "match_reason": "下载器中暂未匹配",
            "can_delete": False, "matched": False,
        })
        entries.append(item)
        original = str(site.get("title") or "")
        canon = normalize_name(original)
        selected: list[tuple[int, str, float]] = []
        exact = by_exact.get(canon, ())
        if exact:
            for index in exact:
                match = _match_record(site, downloader_torrents[index], original, canon, True)
                if match:
                    selected.append((index, match[0], match[1]))
        else:
            candidates = _candidate_indices(site, by_prefix, by_token, counts)
            scored = []
            for index in candidates:
                match = _match_record(site, downloader_torrents[index], original, canon, False)
                if match:
                    scored.append((index, match[0], match[1]))
            if scored:
                scored.sort(key=lambda x: x[2], reverse=True)
                top = scored[0][2]
                selected = [x for x in scored if x[2] >= top - 0.035]
        matches.append(selected)

    # Never assign a downloader hash ambiguously to two different site rows.
    reverse = Counter(index for group in matches for index, _, _ in group)
    stats = {"eligible": len(entries), "linked": 0, "exact": 0,
             "similar": 0, "ambiguous": 0, "unmatched": 0,
             "deletable": 0}
    for item, group in zip(entries, matches):
        if not group:
            stats["unmatched"] += 1
            continue
        unique = {(downloader_torrents[index].get("downloader") or "").strip()
                  for index, _, _ in group}
        item["downloaders"] = sorted(x for x in unique if x)
        item["downloader"] = " / ".join(item["downloaders"])
        item["matched"] = True
        stats["linked"] += 1
        if len(group) != 1 or any(reverse[index] > 1 for index, _, _ in group) \
                or site_names[normalize_name(item.get("title"))] != 1:
            item["match_status"] = "ambiguous"
            item["match_reason"] = "多个候选下载器任务或站点记录，禁止直接删除"
            stats["ambiguous"] += 1
            continue
        index, match_type, _ = group[0]
        torrent = downloader_torrents[index]
        item["match_status"] = match_type
        stats[match_type] += 1
        for field in ("upspeed", "dlspeed", "eta", "ratio", "path",
                      "cur_seeders", "cur_leechers", "tracker", "added", "progress"):
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
        elif match_type == "similar":
            item["match_reason"] = "名称近似匹配，仅供查看，不允许直接删除"
        elif not tracker_ok:
            item["match_status"] = "unverified"
            item["match_reason"] = "Tracker 未确认是憨憨站，仅供查看"
        else:
            item["match_reason"] = "名称精确匹配且已确认憨憨站 Tracker"
        if (match_type == "exact" and tracker_ok and complete
                and torrent.get("hash") and item["downloader"]):
            item["hash"] = str(torrent["hash"])
            item["can_delete"] = True
            stats["deletable"] += 1
    return entries, stats
