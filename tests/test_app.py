import os
import unittest
from html.parser import HTMLParser
from unittest.mock import Mock, patch

import app as app_module


class ButtonParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.button_ids = []

    def handle_starttag(self, tag, attrs):
        if tag == "button":
            self.button_ids.append(dict(attrs).get("id"))


class ChatRouteTests(unittest.TestCase):
    def setUp(self):
        with app_module.chat_requests_lock:
            app_module.chat_requests.clear()
        self.environment = patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-only-placeholder",
                "OPENROUTER_MODEL": "test/vision-model",
            },
        )
        self.environment.start()
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.environment.stop()

    def test_health_does_not_expose_api_key(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "ok")
        self.assertTrue(response.json["api_configured"])
        self.assertTrue(response.json["model_configured"])
        self.assertEqual(response.json["model"], "test/vision-model")
        self.assertNotIn(b"test-only-placeholder", response.data)

    def test_health_reports_missing_api_configuration(self):
        with patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "", "OPENROUTER_MODEL": ""},
        ):
            response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "ok")
        self.assertFalse(response.json["api_configured"])
        self.assertFalse(response.json["model_configured"])
        self.assertIsNone(response.json["model"])

    def test_home_serves_index_html(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<title>B.E.A", response.data)
        response.close()

    def test_hands_free_voice_and_periodic_vision_controls_are_present(self):
        response = self.client.get("/")
        html = response.get_data(as_text=True)
        parser = ButtonParser()
        parser.feed(html)

        self.assertEqual(parser.button_ids, ["startSystem", "muteMic"])
        self.assertNotIn('id="btnTalk"', html)
        self.assertNotIn('id="btnDescribe"', html)
        self.assertIn('aria-pressed="false"', html)
        self.assertIn('recognition.abort()', html)
        self.assertIn('if (busy || micMuted || micBlocked) return;', html)
        self.assertIn("environmentScanIntervalMs: 60000", html)
        self.assertIn("scheduleEnvironmentScan(CONFIG.firstEnvironmentScanMs)", html)
        self.assertIn('document.visibilityState !== "visible"', html)

    def test_chat_sends_configured_model_and_returns_answer(self):
        upstream = Mock()
        upstream.ok = True
        upstream.json.return_value = {
            "choices": [{"message": {"content": "Há uma porta à frente."}}]
        }
        messages = [
            {"role": "system", "content": "Responda em português."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "O que há à frente?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64,ZmFrZQ=="},
                    },
                ],
            },
        ]

        with patch("app.requests.post", return_value=upstream) as post:
            response = self.client.post("/api/chat", json={"messages": messages})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json,
            {"choices": [{"message": {"content": "Há uma porta à frente."}}]},
        )
        self.assertEqual(post.call_args.kwargs["json"]["model"], "test/vision-model")
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 600)
        self.assertEqual(post.call_args.kwargs["json"]["messages"], messages)
        self.assertTrue(post.call_args.kwargs["headers"]["HTTP-Referer"].startswith("http"))
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        )

    def test_missing_api_key_returns_configuration_error(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            response = self.client.post("/api/chat", json={"messages": []})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["code"], "api_key_missing")
        self.assertIn("não está configurada", response.json["error"])

    def test_invalid_role_returns_bad_request(self):
        response = self.client.post(
            "/api/chat",
            json={"messages": [{"role": [], "content": "invalid"}]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("inválida", response.json["error"])

    def test_invalid_image_url_returns_bad_request(self):
        response = self.client.post(
            "/api/chat",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": "https://example.invalid/photo.jpg"},
                            }
                        ],
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 400)

    def test_upstream_errors_are_sanitized(self):
        upstream = Mock(ok=False, status_code=429, text="sensitive upstream details")

        with patch("app.requests.post", return_value=upstream):
            response = self.client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "Olá"}]},
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json["code"], "provider_rate_limited")
        self.assertNotIn(b"sensitive upstream details", response.data)

    def test_unknown_model_is_reported_as_provider_model_error(self):
        upstream = Mock(ok=False, status_code=404)

        with patch("app.requests.post", return_value=upstream):
            response = self.client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "Olá"}]},
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json["code"], "provider_model_not_found")
        self.assertIn("OPENROUTER_MODEL", response.json["error"])

    def test_provider_authentication_and_credits_have_distinct_errors(self):
        for upstream_status, expected_code in (
            (401, "provider_authentication"),
            (402, "provider_credits"),
            (503, "provider_unavailable"),
        ):
            with self.subTest(status=upstream_status):
                upstream = Mock(ok=False, status_code=upstream_status)
                with patch("app.requests.post", return_value=upstream):
                    response = self.client.post(
                        "/api/chat",
                        json={"messages": [{"role": "user", "content": "Olá"}]},
                    )
                self.assertEqual(response.json["code"], expected_code)

    def test_text_only_chat_is_forwarded(self):
        upstream = Mock()
        upstream.ok = True
        upstream.json.return_value = {
            "choices": [{"message": {"content": "Resposta de texto."}}]
        }
        messages = [{"role": "user", "content": "Responda sem imagem."}]

        with patch("app.requests.post", return_value=upstream) as post:
            response = self.client.post("/api/chat", json={"messages": messages})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(post.call_args.kwargs["json"]["messages"], messages)

    def test_text_blocks_in_provider_content_are_combined(self):
        upstream = Mock()
        upstream.ok = True
        upstream.status_code = 200
        upstream.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "Resposta em "},
                            {"type": "text", "text": "blocos."},
                        ]
                    },
                    "finish_reason": "stop",
                }
            ]
        }

        with patch("app.requests.post", return_value=upstream):
            response = self.client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "Olá"}]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json["choices"][0]["message"]["content"],
            "Resposta em\nblocos.",
        )

    def test_non_json_success_from_provider_returns_specific_error_and_safe_log(self):
        upstream = Mock(ok=True, status_code=200)
        upstream.json.side_effect = ValueError("private response body")
        upstream.headers = {"Content-Type": "text/html"}

        with patch("app.requests.post", return_value=upstream), self.assertLogs(
            "app", level="WARNING"
        ) as captured:
            response = self.client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "Olá"}]},
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json["code"], "provider_invalid_response")
        self.assertIn("HTTP 200", "\n".join(captured.output))
        self.assertNotIn("private response body", "\n".join(captured.output))

    def test_unexpected_provider_json_shape_returns_invalid_response(self):
        for payload in ([], {"choices": []}, {"choices": [{"message": None}]}):
            with self.subTest(payload=payload):
                upstream = Mock(ok=True, status_code=200)
                upstream.json.return_value = payload
                with patch("app.requests.post", return_value=upstream):
                    response = self.client.post(
                        "/api/chat",
                        json={"messages": [{"role": "user", "content": "Olá"}]},
                    )

                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.json["code"], "provider_invalid_response")
                self.assertIn("OpenRouter", response.json["error"])

    def test_empty_and_reasoning_only_provider_responses_are_distinguished(self):
        cases = (
            (
                {"content": "   "},
                "stop",
                "provider_empty_response",
                "sem texto final",
            ),
            (
                {"content": "", "reasoning": "private reasoning that must not leak"},
                "stop",
                "provider_no_answer",
                "não forneceu uma resposta final",
            ),
            (
                {"content": ""},
                "length",
                "provider_incomplete_response",
                "interrompida",
            ),
        )
        for message, finish_reason, expected_code, expected_message in cases:
            with self.subTest(code=expected_code):
                upstream = Mock(ok=True, status_code=200)
                upstream.json.return_value = {
                    "choices": [
                        {"message": message, "finish_reason": finish_reason}
                    ]
                }
                with patch("app.requests.post", return_value=upstream):
                    response = self.client.post(
                        "/api/chat",
                        json={"messages": [{"role": "user", "content": "Olá"}]},
                    )

                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.json["code"], expected_code)
                self.assertIn(expected_message, response.json["error"])
                self.assertNotIn("private reasoning", response.get_data(as_text=True))

    def test_provider_http_errors_include_status_in_safe_logs(self):
        upstream = Mock(ok=False, status_code=429)
        upstream.json.return_value = {
            "error": {
                "message": "private account detail: rate limit exceeded",
                "code": "rate_limit",
            }
        }

        with patch("app.requests.post", return_value=upstream), self.assertLogs(
            "app", level="WARNING"
        ) as captured:
            response = self.client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "Olá"}]},
            )

        logs = "\n".join(captured.output)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json["code"], "provider_rate_limited")
        self.assertIn("HTTP 429", logs)
        self.assertIn("provider_rate_limited", logs)
        self.assertNotIn("private account detail", logs)

    def test_upstream_timeout_returns_gateway_timeout(self):
        with patch("app.requests.post", side_effect=app_module.requests.Timeout):
            response = self.client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "Olá"}]},
            )

        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json["code"], "provider_timeout")

    def test_provider_connection_error_is_reported_separately(self):
        with patch(
            "app.requests.post",
            side_effect=app_module.requests.ConnectionError("upstream unavailable"),
        ):
            response = self.client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "Olá"}]},
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json["code"], "provider_unavailable")

    def test_chat_rate_limit_protects_provider_usage(self):
        upstream = Mock()
        upstream.ok = True
        upstream.json.return_value = {
            "choices": [{"message": {"content": "Resposta."}}]
        }

        with patch.object(app_module, "CHAT_RATE_LIMIT", 1), patch(
            "app.requests.post", return_value=upstream
        ) as post:
            payload = {"messages": [{"role": "user", "content": "Olá"}]}
            first = self.client.post("/api/chat", json=payload)
            second = self.client.post("/api/chat", json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json["code"], "request_rate_limited")
        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
