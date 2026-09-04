import base64
import html
import json
import lzma
import os
import random
import re
import secrets
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timedelta
from functools import cache
from pathlib import Path

import httpx
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles


ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data" / "chat.json"
STATIC_DIR = ROOT / "static"
OPENLUX_URL = "https://api.openlux.ai/v1/chat/completions"
MODEL = "gemini-3.7-flash"
LOVE_WORDS = ("爱你", "喜欢你", "想你", "宝宝", "哥哥", "抱抱")
SHOWCASE_WORDS = ("爱", "哥哥", "宝宝", "爱你", "抱抱")
ROLES = ("self", "partner")

load_dotenv(ROOT / ".env")


def visible_text(content: str, message_type: str | int) -> str:
    if message_type == "文本":
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", content).strip()
    if message_type != "文件/链接/卡片" or "<appmsg" not in content:
        return ""
    try:
        root = ET.fromstring(content.strip())
    except ET.ParseError:
        return ""
    if root.findtext("appmsg/type") != "57":
        return ""
    return html.unescape(root.findtext("appmsg/title") or "").strip()


@cache
def archive() -> dict:
    data_file = Path(os.environ.get("CHAT_DATA_FILE", DATA_FILE))
    if data_file.name.endswith(".xz.b64"):
        data = json.loads(lzma.decompress(base64.b64decode(data_file.read_bytes())))
    else:
        data = json.loads(data_file.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise RuntimeError("不支持的聊天数据版本，请重新运行导出 CLI")
    owner_name = data["owner"]["name"]
    partner_name = data["partner"]["name"]
    for index, message in enumerate(data["messages"], 1):
        message["id"] = index
        message["sender"] = (
            "self"
            if message["sender_name"] == owner_name
            else "partner"
            if message["sender_name"] == partner_name
            else "system"
        )
        message["text"] = visible_text(message["content"], message["type"])
    return data


def count_terms(messages: list[dict], terms: list[str]) -> dict:
    counts = {role: {term: 0 for term in terms} for role in ROLES}
    matched = {role: {term: 0 for term in terms} for role in ROLES}
    for message in messages:
        role = message["sender"]
        if role not in ROLES or not message["text"]:
            continue
        text = message["text"].casefold()
        for term in terms:
            hits = text.count(term.casefold())
            counts[role][term] += hits
            matched[role][term] += bool(hits)
    return {"occurrences": counts, "messages": matched}


def longest_streak(active_days: set[date]) -> int:
    best = current = 0
    previous = None
    for day in sorted(active_days):
        current = current + 1 if previous and day == previous + timedelta(days=1) else 1
        best = max(best, current)
        previous = day
    return best


def make_summary(data: dict) -> dict:
    messages = [message for message in data["messages"] if message["sender"] in ROLES]
    names = {"self": data["owner"]["name"], "partner": data["partner"]["name"]}
    by_sender = {
        role: {
            "messages": sum(message["sender"] == role for message in messages),
            "characters": sum(
                sum(not char.isspace() for char in message["text"])
                for message in messages
                if message["sender"] == role
            ),
        }
        for role in ROLES
    }

    first_day = date.fromisoformat(messages[0]["time"][:10])
    last_day = date.fromisoformat(messages[-1]["time"][:10])
    daily_counter = {role: Counter() for role in ROLES}
    periods = {
        role: {"凌晨": 0, "清晨": 0, "白天": 0, "夜晚": 0}
        for role in ROLES
    }
    for message in messages:
        stamp = datetime.fromisoformat(message["time"])
        daily_counter[message["sender"]][stamp.date().isoformat()] += 1
        period = "凌晨" if stamp.hour < 6 else "清晨" if stamp.hour < 9 else "白天" if stamp.hour < 18 else "夜晚"
        periods[message["sender"]][period] += 1

    days = []
    cursor = first_day
    while cursor <= last_day:
        key = cursor.isoformat()
        days.append(
            {
                "date": key,
                "self": daily_counter["self"][key],
                "partner": daily_counter["partner"][key],
            }
        )
        cursor += timedelta(days=1)
    active_days = {
        date.fromisoformat(day["date"])
        for day in days
        if day["self"] + day["partner"]
    }
    peak = max(days, key=lambda item: item["self"] + item["partner"])
    candidates = [
        message
        for message in messages
        if 1 <= len(message["text"]) <= 120
        and any(word in message["text"] for word in SHOWCASE_WORDS)
    ]
    showcase = random.sample(candidates, min(12, len(candidates)))

    return {
        "names": names,
        "range": {"start": messages[0]["time"], "end": messages[-1]["time"]},
        "total_messages": len(messages),
        "by_sender": by_sender,
        "active_days": len(active_days),
        "calendar_days": (last_day - first_day).days + 1,
        "longest_streak": longest_streak(active_days),
        "peak_day": {**peak, "total": peak["self"] + peak["partner"]},
        "daily": days,
        "periods": periods,
        "love_words": count_terms(messages, list(LOVE_WORDS)),
        "showcase": [
            {
                "id": message["id"],
                "time": message["time"],
                "sender": message["sender"],
                "sender_name": message["sender_name"],
                "text": message["text"],
            }
            for message in showcase
        ],
    }


def search_archive(keywords: list[str], limit: int = 30) -> list[dict]:
    needles = [keyword.casefold() for keyword in keywords]
    matches = []
    for message in archive()["messages"]:
        if message["sender"] not in ROLES or not message["text"]:
            continue
        text = message["text"].casefold()
        hit_words = [keywords[i] for i, needle in enumerate(needles) if needle in text]
        if hit_words:
            matches.append(
                {
                    "id": message["id"],
                    "time": message["time"],
                    "sender": message["sender_name"],
                    "content": message["text"],
                    "matched_keywords": hit_words,
                }
            )
        if len(matches) == limit:
            break
    return matches


def finish_answer(answer: str, sources: list[dict]) -> str:
    answer = answer.strip()
    if sources and not any(f"消息#{source['id']}" in answer for source in sources):
        source = sources[0]
        quote = source["content"][:119] + "…" if len(source["content"]) > 120 else source["content"]
        stamp = source["time"][:16].replace("T", " ")
        citation = f"\n\n【消息#{source['id']} · {stamp} · {source['sender']}】“{quote}”"
        answer = answer[: max(0, 2000 - len(citation))].rstrip() + citation
    return answer[:2000]


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_chat",
            "description": "按一个或多个关键词查询双方真实聊天记录，返回时间顺序最前面的至多30条匹配消息。回答前必须调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 5,
                        "description": "从问题提炼的1至5个中文关键词",
                    }
                },
                "required": ["keywords"],
                "additionalProperties": False,
            },
        },
    }
]


async def completion(client: httpx.AsyncClient, messages: list[dict], tool_choice) -> dict:
    response = await client.post(
        OPENLUX_URL,
        headers={"Authorization": f"Bearer {os.environ['APIKEY']}"},
        json={
            "model": MODEL,
            "messages": messages,
            "tools": TOOLS,
            "tool_choice": tool_choice,
            "temperature": 0.75,
            "max_tokens": 1600,
        },
    )
    response.raise_for_status()
    payload = response.json()
    return payload["choices"][0]["message"]


async def ask_ai(question: str) -> str:
    data = archive()
    names = f"{data['owner']['name']}（self）和 {data['partner']['name']}（partner）"
    messages = [
        {
            "role": "system",
            "content": (
                f"你是{names}的专属聊天回忆分析师。语气必须青春、可爱、阳光，但结论要诚实。"
                "回答前必须调用 search_chat 查证；最多调用两次。每个事实性结论都要引用工具返回的真实消息，"
                "格式为【消息#编号 · 日期时间 · 发送者】“原文”。不得编造原文、日期或心理诊断；证据不足就直说。"
                "使用简洁中文，最终回答不超过2000个字符。"
            ),
        },
        {"role": "user", "content": question},
    ]
    first_choice = {"type": "function", "function": {"name": "search_chat"}}
    tool_uses = 0
    sources = []

    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            reply = await completion(client, messages, first_choice if tool_uses == 0 else "auto")
            messages.append(reply)
            calls = reply.get("tool_calls") or []
            if not calls:
                return finish_answer(reply.get("content") or "", sources)

            for call in calls:
                if tool_uses >= 2:
                    result = {"error": "工具调用次数已用完，请根据已有结果回答"}
                else:
                    tool_uses += 1
                    try:
                        arguments = json.loads(call["function"]["arguments"])
                        keywords = arguments["keywords"]
                        if not isinstance(keywords, list) or not 1 <= len(keywords) <= 5:
                            raise ValueError("keywords 必须是包含1至5项的数组")
                        keywords = [str(keyword).strip()[:30] for keyword in keywords if str(keyword).strip()]
                        if not keywords:
                            raise ValueError("关键词不能为空")
                        result = {"results": search_archive(keywords), "count": 0}
                        result["count"] = len(result["results"])
                        sources.extend(result["results"])
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                        result = {"error": str(exc)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

            if tool_uses >= 2:
                reply = await completion(client, messages, "none")
                return finish_answer(reply.get("content") or "", sources)


async def homepage(_: Request) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


async def summary(_: Request) -> JSONResponse:
    return JSONResponse(make_summary(archive()))


async def search(request: Request) -> JSONResponse:
    query = request.query_params.get("q", "").strip()
    if not query or len(query) > 40:
        raise HTTPException(400, "查询内容需为1至40个字符")
    human_messages = [message for message in archive()["messages"] if message["sender"] in ROLES]
    counts = count_terms(human_messages, [query])
    return JSONResponse(
        {
            "query": query,
            "occurrences": {role: counts["occurrences"][role][query] for role in ROLES},
            "messages": {role: counts["messages"][role][query] for role in ROLES},
        }
    )


async def ask(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "请求必须是 JSON")
    question = body.get("question", "") if isinstance(body, dict) else ""
    if not isinstance(question, str) or not question.strip() or len(question.strip()) > 500:
        raise HTTPException(400, "问题需为1至500个字符")
    if not os.environ.get("APIKEY"):
        raise HTTPException(503, "服务端尚未配置 APIKEY")
    try:
        answer = await ask_ai(question.strip())
    except httpx.TimeoutException:
        raise HTTPException(504, "AI 思考超时，请稍后再试")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"AI 服务返回 {exc.response.status_code}")
    except (httpx.RequestError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        raise HTTPException(502, "AI 服务响应异常")
    return JSONResponse({"answer": answer, "model": MODEL})


async def password_gate(request: Request, call_next):
    password = os.environ.get("SITE_PASSWORD")
    supplied = request.headers.get("X-Ourdays-Password", "")
    if (
        password
        and request.url.path.startswith("/api/")
        and not secrets.compare_digest(supplied.encode(), password.encode())
    ):
        return JSONResponse({"detail": "请输入访问密码"}, status_code=401)
    return await call_next(request)


routes = [
    Route("/", homepage),
    Route("/api/summary", summary),
    Route("/api/search", search),
    Route("/api/ask", ask, methods=["POST"]),
    Mount("/static", app=StaticFiles(directory=STATIC_DIR), name="static"),
]
app = Starlette(routes=routes)
app.add_middleware(BaseHTTPMiddleware, dispatch=password_gate)
