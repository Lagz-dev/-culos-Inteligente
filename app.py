import os
import re
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_QUESTION_LENGTH = 5000
MAX_REQUEST_BYTES = 8 * 1024 * 1024
CHAT_RATE_LIMIT = 10
CHAT_RATE_WINDOW_SECONDS = 60
IMAGE_DATA_URL = re.compile(r"^data:image/jpeg;base64,[A-Za-z0-9+/]*={0,2}$")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
chat_requests = defaultdict(deque)
chat_requests_lock = threading.Lock()


def error_response(message, status, code):
    return jsonify({"error": message, "code": code}), status


def chat_rate_limited(client_ip):
    now = time.monotonic()
    cutoff = now - CHAT_RATE_WINDOW_SECONDS
    with chat_requests_lock:
        timestamps = chat_requests[client_ip]
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()
        if len(timestamps) >= CHAT_RATE_LIMIT:
            return True
        timestamps.append(now)
        return False


def validate_messages(messages):
    if not isinstance(messages, list) or not 1 <= len(messages) <= 10:
        return "A requisição precisa conter entre 1 e 10 mensagens."

    for message in messages:
        role = message.get("role") if isinstance(message, dict) else None
        if not isinstance(role, str) or role not in {"system", "user", "assistant"}:
            return "Uma mensagem da requisição é inválida."

        content = message.get("content")
        if isinstance(content, str):
            if len(content) > MAX_QUESTION_LENGTH:
                return "O texto da mensagem excede o limite permitido."
            continue

        if role != "user" or not isinstance(content, list) or not content:
            return "O conteúdo da mensagem é inválido."

        for item in content:
            if not isinstance(item, dict):
                return "Um item da mensagem é inválido."
            if item.get("type") == "text":
                text = item.get("text")
                if not isinstance(text, str) or len(text) > MAX_QUESTION_LENGTH:
                    return "O texto da mensagem é inválido ou excede o limite permitido."
            elif item.get("type") == "image_url":
                image_url = item.get("image_url")
                if not isinstance(image_url, dict):
                    return "A imagem enviada é inválida."
                image_data = image_url.get("url")
                if (
                    not isinstance(image_data, str)
                    or not IMAGE_DATA_URL.fullmatch(image_data)
                    or len(image_data) > MAX_IMAGE_BYTES * 4 // 3 + 64
                ):
                    return "A imagem deve ser JPEG e respeitar o limite de tamanho."
            else:
                return "O tipo de conteúdo enviado não é aceito."

    return None


@app.get("/")
def home():
    return send_from_directory(BASE_DIR, "index1.html")


@app.get("/api/health")
def health():
    model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL).strip()
    model_is_valid = bool(model) and len(model) <= 200
    return jsonify(
        {
            "status": "ok",
            "api_configured": bool(os.getenv("OPENROUTER_API_KEY", "").strip()),
            "model_configured": model_is_valid,
            "model": model if model_is_valid else None,
        }
    )


@app.post("/api/chat")
def chat():
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        app.logger.error("A variável OPENROUTER_API_KEY não está configurada.")
        return error_response(
            "A integração de IA não está configurada no servidor.",
            503,
            "api_key_missing",
        )

    if not request.is_json:
        return error_response("Envie a requisição no formato JSON.", 415, "invalid_content_type")

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("O corpo da requisição JSON é inválido.", 400, "invalid_json")

    messages = data.get("messages")
    validation_error = validate_messages(messages)
    if validation_error:
        return error_response(validation_error, 400, "invalid_request")

    model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL).strip()
    if not model or len(model) > 200:
        app.logger.error("A variável OPENROUTER_MODEL está ausente ou inválida.")
        return error_response(
            "O modelo de IA não está configurado corretamente no servidor.",
            503,
            "model_configuration_error",
        )

    client_ip = request.remote_addr or "unknown"
    if chat_rate_limited(client_ip):
        return error_response(
            "Muitas solicitações foram feitas deste endereço. Aguarde um minuto e tente novamente.",
            429,
            "request_rate_limited",
        )

    try:
        upstream = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": request.url_root.rstrip("/"),
                "X-Title": "B.E.A. - Assistente de Visão",
            },
            json={"model": model, "max_tokens": 200, "messages": messages},
            timeout=(10, 40),
        )
    except requests.Timeout as exc:
        app.logger.warning("Timeout na chamada OpenRouter (%s).", type(exc).__name__)
        return error_response("A API de IA demorou demais para responder.", 504, "provider_timeout")
    except requests.RequestException as exc:
        app.logger.warning("Falha na chamada OpenRouter (%s).", type(exc).__name__)
        return error_response(
            "Não foi possível alcançar o serviço de IA. Tente novamente.",
            502,
            "provider_unavailable",
        )

    if not upstream.ok:
        upstream_status = upstream.status_code
        app.logger.warning("A OpenRouter retornou HTTP %s.", upstream_status)
        if upstream_status in {401, 403}:
            return error_response(
                "A OpenRouter recusou a credencial configurada. Confira OPENROUTER_API_KEY no Render.",
                502,
                "provider_authentication",
            )
        if upstream_status == 402:
            return error_response(
                "A conta da OpenRouter não tem créditos disponíveis para esta solicitação.",
                402,
                "provider_credits",
            )
        if upstream_status == 404:
            return error_response(
                "O modelo configurado não foi encontrado na OpenRouter. Confira OPENROUTER_MODEL no Render.",
                502,
                "provider_model_not_found",
            )
        if upstream_status == 429:
            return error_response(
                "A OpenRouter limitou as solicitações. Aguarde e tente novamente.",
                429,
                "provider_rate_limited",
            )
        if upstream_status >= 500:
            return error_response(
                "A OpenRouter está temporariamente indisponível. Tente novamente.",
                502,
                "provider_unavailable",
            )
        return error_response(
            "A OpenRouter recusou a solicitação. Verifique se o modelo aceita o conteúdo enviado.",
            502,
            "provider_request_rejected",
        )

    try:
        result = upstream.json()
        answer = result["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        app.logger.warning("A API da OpenRouter retornou uma resposta inválida.")
        return error_response(
            "A API de IA retornou uma resposta inválida.",
            502,
            "provider_invalid_response",
        )

    if not isinstance(answer, str) or not answer.strip():
        app.logger.warning("A API da OpenRouter retornou uma resposta sem texto.")
        return error_response("A API de IA retornou uma resposta vazia.", 502, "provider_empty_response")

    return jsonify({"choices": [{"message": {"content": answer}}]})


@app.errorhandler(413)
def request_too_large(_error):
    return error_response(
        "A imagem ou requisição excede o limite de tamanho.",
        413,
        "request_too_large",
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
