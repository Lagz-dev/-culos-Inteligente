import os
import unittest
from unittest.mock import Mock, patch

import app as app_module


class ChatRouteTests(unittest.TestCase):
    def setUp(self):
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
        self.assertEqual(response.json, {"status": "ok", "api_configured": True})
        self.assertNotIn(b"test-only-placeholder", response.data)

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
        self.assertEqual(post.call_args.kwargs["json"]["messages"], messages)
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        )

    def test_missing_api_key_returns_configuration_error(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            response = self.client.post("/api/chat", json={"messages": []})

        self.assertEqual(response.status_code, 503)
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
        self.assertNotIn(b"sensitive upstream details", response.data)

    def test_upstream_timeout_returns_gateway_timeout(self):
        with patch("app.requests.post", side_effect=app_module.requests.Timeout):
            response = self.client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "Olá"}]},
            )

        self.assertEqual(response.status_code, 504)


if __name__ == "__main__":
    unittest.main()
