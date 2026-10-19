import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o"
MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_QUESTION_LENGTH = 5000
MAX_REQUEST_BYTES = 8 * 1024 * 1024
IMAGE_DATA_URL = re.compile(r"^data:image/jpeg;base64,[A-Za-z0-9+/]*={0,2}$")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES


def error_response(message, status):
    return jsonify({"error": message}), status


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
    return jsonify({"status": "ok", "api_configured": bool(os.getenv("OPENROUTER_API_KEY"))})


@app.post("/api/chat")
def chat():
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return error_response("A integração de IA não está configurada no servidor.", 503)

    if not request.is_json:
        return error_response("Envie a requisição no formato JSON.", 415)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("O corpo da requisição JSON é inválido.", 400)

    messages = data.get("messages")
    validation_error = validate_messages(messages)
    if validation_error:
        return error_response(validation_error, 400)

    model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL).strip()
    if not model or len(model) > 200:
        return error_response("O modelo de IA configurado no servidor é inválido.", 500)

    try:
        upstream = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:5000",
                "X-Title": "B.E.A. - Assistente de Visão",
            },
            json={"model": model, "max_tokens": 200, "messages": messages},
            timeout=(10, 40),
        )
    except requests.Timeout:
        return error_response("A API de IA demorou demais para responder.", 504)
    except requests.RequestException:
        app.logger.warning("Falha ao conectar à API da OpenRouter.")
        return error_response("Não foi possível conectar à API de IA.", 502)

    if not upstream.ok:
        status = upstream.status_code if 400 <= upstream.status_code < 500 else 502
        return error_response("A API de IA recusou ou não conseguiu processar a solicitação.", status)

    try:
        result = upstream.json()
        answer = result["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        app.logger.warning("A API da OpenRouter retornou uma resposta inválida.")
        return error_response("A API de IA retornou uma resposta inválida.", 502)

    if not isinstance(answer, str) or not answer.strip():
        app.logger.warning("A API da OpenRouter retornou uma resposta sem texto.")
        return error_response("A API de IA retornou uma resposta vazia.", 502)

    return jsonify({"choices": [{"message": {"content": answer}}]})


@app.errorhandler(413)
def request_too_large(_error):
    return error_response("A imagem ou requisição excede o limite de tamanho.", 413)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
