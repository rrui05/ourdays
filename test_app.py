import base64
import json
import lzma
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import app


class AppTest(unittest.TestCase):
    def test_render_secret_archive(self):
        payload = {
            "schema_version": 1,
            "owner": {"name": "A"},
            "partner": {"name": "B"},
            "messages": [
                {
                    "time": "2026-07-22T22:00:00+08:00",
                    "sender_name": "A",
                    "type": "文本",
                    "content": "爱你",
                }
            ],
        }
        encoded = base64.b64encode(lzma.compress(json.dumps(payload, ensure_ascii=False).encode()))
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "chat.json.xz.b64"
            secret.write_bytes(encoded)
            with patch.dict(os.environ, {"CHAT_DATA_FILE": str(secret)}):
                app.archive.cache_clear()
                self.assertEqual(app.archive()["messages"][0]["text"], "爱你")
        app.archive.cache_clear()

    def test_text_and_statistics(self):
        self.assertEqual(app.visible_text("爱你爱你", "文本"), "爱你爱你")
        reply = "<msg><appmsg><title>抱抱你</title><type>57</type></appmsg></msg>"
        self.assertEqual(app.visible_text(reply, "文件/链接/卡片"), "抱抱你")

        data = {
            "owner": {"name": "A"},
            "partner": {"name": "B"},
            "messages": [
                {"id": 1, "time": "2026-07-22T22:00:00+08:00", "sender": "self", "sender_name": "A", "text": "爱你爱你"},
                {"id": 2, "time": "2026-07-23T08:00:00+08:00", "sender": "partner", "sender_name": "B", "text": "我也爱你"},
            ],
        }
        summary = app.make_summary(data)
        self.assertEqual(summary["total_messages"], 2)
        self.assertEqual(summary["by_sender"]["self"]["characters"], 4)
        self.assertEqual(summary["love_words"]["occurrences"]["self"]["爱你"], 2)
        self.assertEqual(summary["longest_streak"], 2)

    def test_search_stops_at_thirty(self):
        messages = [
            {"id": i, "time": "2026-07-22T22:00:00+08:00", "sender": "self", "sender_name": "A", "text": "宝宝"}
            for i in range(40)
        ]
        with patch("app.archive", return_value={"messages": messages}):
            self.assertEqual(len(app.search_archive(["宝宝"])), 30)

    def test_longest_streak_breaks_on_empty_day(self):
        days = {date(2026, 7, 22), date(2026, 7, 23), date(2026, 7, 25)}
        self.assertEqual(app.longest_streak(days), 2)

    def test_answer_gets_a_real_citation_without_truncation(self):
        source = {"id": 7, "time": "2026-07-22T22:00:00+08:00", "sender": "A", "content": "爱你"}
        original = "当然有呀。" + "甜" * 2100
        answer = app.finish_answer(original, [source])
        self.assertTrue(answer.startswith(original))
        self.assertIn("【消息#7 · 2026-07-22 22:00 · A】“爱你”", answer)


class AgentLoopTest(unittest.IsolatedAsyncioTestCase):
    async def test_password_gate_protects_apis(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/search",
            "headers": [],
            "query_string": b"",
            "scheme": "https",
            "server": ("test", 443),
            "client": ("test", 1),
        }
        call_next = AsyncMock(return_value=app.JSONResponse({"ok": True}))
        with patch.dict(os.environ, {"SITE_PASSWORD": "sunset-rose"}):
            response = await app.password_gate(app.Request(scope), call_next)
            self.assertEqual(response.status_code, 401)
            scope["headers"] = [(b"x-ourdays-password", b"sunset-rose")]
            response = await app.password_gate(app.Request(scope), call_next)
            self.assertEqual(response.status_code, 200)

    async def test_two_tools_then_forced_answer(self):
        tool_replies = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": f"call-{i}", "function": {"name": "search_chat", "arguments": '{"keywords":["爱你"]}'}}
                ],
            }
            for i in range(2)
        ]
        final = {"role": "assistant", "content": "有证据的可爱回答"}
        people = {"owner": {"name": "A"}, "partner": {"name": "B"}}
        with (
            patch("app.archive", return_value=people),
            patch("app.search_archive", return_value=[]),
            patch("app.completion", new_callable=AsyncMock) as mocked,
        ):
            mocked.side_effect = [*tool_replies, final]
            self.assertEqual(await app.ask_ai("谁更会表达爱？"), final["content"])
            self.assertEqual(mocked.await_count, 3)
            self.assertEqual(mocked.await_args_list[-1].args[2], "none")


if __name__ == "__main__":
    unittest.main()
