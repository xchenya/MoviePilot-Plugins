"""Atomic per-instance state and a process lock that survives plugin hot reloads."""
import json
import math
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .protocol import LotteryError, integer, number


def empty_day():
    """Separate locally charged quota from confirmed prize receipts."""
    return {"attempted": 0, "draws": 0, "spent": 0, "change": 0, "compensated": 0, "prizes": {}}


def load(path: Path) -> dict:
    """Never silently discard an unreadable pending order."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "pending": None, "days": {}, "history": []}
    except (OSError, ValueError) as exc:
        raise LotteryError("抽奖状态文件无法读取，请恢复备份，勿删除后重复抽奖") from exc
    if (not isinstance(value, dict) or value.get("version") != 1
            or "pending" not in value
            or not isinstance(value.get("days"), dict)
            or not isinstance(value.get("history"), list)
            or (value.get("pending") is not None and not isinstance(value.get("pending"), dict))):
        raise LotteryError("抽奖状态文件格式异常，已停止")
    try:
        for key, daily in value["days"].items():
            if not re.fullmatch(r"\d+:\d{4}-\d{2}-\d{2}", key) or not isinstance(daily, dict):
                raise ValueError()
            attempted, draws = integer(daily["attempted"]), integer(daily["draws"])
            if draws > attempted or not math.isfinite(float(daily["change"])):
                raise ValueError()
            number(daily["spent"])
            number(daily["compensated"])
            if not isinstance(daily["prizes"], dict) or sum(integer(n) for n in daily["prizes"].values()) != draws:
                raise ValueError()
        pending = value["pending"]
        if pending is not None:
            count = integer(pending["count"])
            daily = value["days"][pending["uid"] + ":" + pending["day"]]
            if not 1 <= count <= 100 or daily["attempted"] - daily["draws"] < count:
                raise ValueError()
            if number(pending["cost"]) <= 0:
                raise ValueError()
            number(pending["before"])
            number(pending["created"])
    except (KeyError, TypeError, ValueError, LotteryError) as exc:
        raise LotteryError("抽奖状态文件不完整，已停止；请恢复备份，勿删除记录后重抽") from exc
    return value


def save(path: Path, state: dict) -> None:
    """Flush a complete state before replacing the old file; never write in place."""
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="lottery-", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        if os.name != "nt":
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    except (OSError, ValueError, TypeError) as exc:
        raise LotteryError("抽奖状态保存失败，已停止；请检查插件数据目录权限和磁盘空间") from exc
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


@contextmanager
def exclusive(path: Path):
    """Exclude overlapping tasks, including another old/new plugin instance."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt
                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
