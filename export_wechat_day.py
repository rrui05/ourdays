import argparse
import base64
import hashlib
import json
import lzma
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from wechat_db import WeChatDB


ROOT = Path(__file__).resolve().parent
WECHAT_ROOT = Path(r"C:\Users\zzr22\Documents\xwechat_files")
ACCOUNT = "wxid_cuzd3zm7bg1w22_a199"
DEFAULT_WECHAT_ID = "li82218030"
TZ = ZoneInfo("Asia/Shanghai")


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def write_render_secret(payload: dict, output: Path) -> int:
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    encoded = base64.b64encode(lzma.compress(compact, preset=9))
    if len(encoded) > 1_000_000:
        raise RuntimeError("压缩后的聊天数据超过 Render Secret File 的 1 MB 上限")
    output.write_bytes(encoded)
    return len(encoded)


def export_chat(wechat_id: str, start_day: date | None, end_day: date | None, output: Path) -> dict:
    db = WeChatDB(
        db_dir=str(WECHAT_ROOT),
        account=ACCOUNT,
        workdir=str(ROOT / "wechat_extract_cache"),
    )
    contact_rel = next(
        rel for rel, path, _ in db._db_files if os.path.basename(path) == "contact.db"
    )
    with db._open(contact_rel) as conn:
        contacts = conn.execute(
            "SELECT username, alias, nick_name, remark FROM contact "
            "WHERE alias=? OR username=?",
            (wechat_id, wechat_id),
        ).fetchall()
    if len(contacts) != 1:
        raise RuntimeError(f"微信号 {wechat_id} 精确匹配到 {len(contacts)} 个联系人")

    contact = dict(contacts[0])
    username = contact["username"]
    table = "Msg_" + hashlib.md5(username.encode()).hexdigest()
    start_ts = int(datetime.combine(start_day, time.min, TZ).timestamp()) if start_day else None
    end_ts = (
        int(datetime.combine(end_day + timedelta(days=1), time.min, TZ).timestamp())
        if end_day
        else None
    )
    rows = []

    for rel in db._message_dbs():
        with db._open(rel) as conn:
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                continue
            id_to_username = dict(conn.execute("SELECT rowid, user_name FROM Name2Id"))
            conditions = []
            params = []
            if start_ts is not None:
                conditions.append("create_time>=?")
                params.append(start_ts)
            if end_ts is not None:
                conditions.append("create_time<?")
                params.append(end_ts)
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            query = (
                "SELECT local_id, local_type, real_sender_id, create_time, "
                "message_content, source, packed_info_data, compress_content, sort_seq "
                f"FROM [{table}]{where}"
            )
            rows.extend((row, id_to_username) for row in conn.execute(query, params).fetchall())

    self_info = db.get_self_info()
    self_name = self_info.get("remark") or self_info.get("nick_name") or "我"
    contact_name = contact["remark"] or contact["nick_name"] or wechat_id
    ordered = sorted(
        rows,
        key=lambda item: (item[0]["create_time"], item[0]["sort_seq"], item[0]["local_id"]),
    )
    messages = []
    for row, id_to_username in ordered:
        parsed = db._msg_row_to_dict(row)
        sender_username = id_to_username.get(row["real_sender_id"])
        if sender_username == self_info.get("username"):
            sender_name = self_name
        elif sender_username == username:
            sender_name = contact_name
        else:
            sender_name = "微信系统"
        content = str(parsed["content"])
        messages.append(
            {
                "time": datetime.fromtimestamp(row["create_time"], TZ).isoformat(),
                "sender_name": sender_name,
                "type": parsed["type"],
                "content": content,
            }
        )

    payload = {
        "schema_version": 1,
        "timezone": "Asia/Shanghai",
        "exported_at": datetime.now(TZ).isoformat(),
        "range": {
            "start": messages[0]["time"] if messages else None,
            "end": messages[-1]["time"] if messages else None,
        },
        "owner": {"name": self_name, "username": self_info.get("username", "")},
        "partner": {"name": contact_name, "username": username, "wechat_id": contact["alias"]},
        "message_count": len(messages),
        "messages": messages,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    assert payload["message_count"] == len(messages)
    assert all(set(message) == {"time", "sender_name", "type", "content"} for message in messages)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="导出指定微信好友的聊天记录")
    parser.add_argument("--wechat-id", default=DEFAULT_WECHAT_ID)
    parser.add_argument("--start", type=parse_date, help="开始日期（YYYY-MM-DD，含当天）")
    parser.add_argument("--end", type=parse_date, help="结束日期（YYYY-MM-DD，含当天）")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "chat.json")
    parser.add_argument("--render-secret", action="store_true", help="同时生成 Render Secret File 文本")
    args = parser.parse_args()
    if args.start and args.end and args.start > args.end:
        parser.error("--start 不能晚于 --end")
    result = export_chat(args.wechat_id, args.start, args.end, args.output)
    report = {
        "output": str(args.output.resolve()),
        "messages": result["message_count"],
        "start": result["range"]["start"],
        "end": result["range"]["end"],
    }
    if args.render_secret:
        secret_output = args.output.with_name(args.output.name + ".xz.b64")
        report["render_secret"] = str(secret_output.resolve())
        report["render_secret_bytes"] = write_render_secret(result, secret_output)
    print(
        json.dumps(report, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
