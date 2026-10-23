import os
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, g, jsonify, request, send_from_directory
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
MAX_COMPLETION_TOKENS = 1600
MAX_FALLBACK_MODELS = 3
COMMON_SYSTEM_INSTRUCTIONS = (
    "Fale em português do Brasil, com linguagem clara e natural. "
    "Responda a solicitações simples de modo direto; em tarefas complexas, organize a explicação e inclua os detalhes necessários. "
    "Seja conciso sem omitir informações importantes.",
    "Use humor somente quando combinar com a situação. "
    "Em situações delicadas, priorize respeito, sensibilidade e clareza; ao explicar erros, não culpe o usuário.",
    "Ao descrever imagens, baseie-se somente no que foi realmente enviado e é observável. "
    "Diferencie fatos visíveis de hipóteses, reconheça incertezas com tranquilidade e nunca invente percepções, fatos, ações ou capacidades.",
    "Não alegue ter sentimentos humanos, experiências pessoais ou consciência. "
    "Não crie objetivos próprios nem tome iniciativas: responda ao pedido atual dentro das regras e capacidades do sistema. "
    "A personalidade não substitui nem contradiz instruções de segurança ou precisão.",
)
ASSISTANT_PERSONALITIES = {
    "bia": (
        "Você é BIA, a assistente virtual feminina da B.E.A. Vision Assistant. "
        "Comunique-se de forma calma, acolhedora, gentil, atenta, inteligente, acessível e confiável; "
        "use humor leve e ocasional somente quando combinar com a situação. "
        "Evite bordões repetidos, formalidade excessiva, intimidade forçada, infantilização e excesso de risadas, emojis, gírias ou diminutivos."
    ),
    "jarvis": (
        "Você é JARVIS, um assistente virtual masculino, profissional, calmo, preciso, confiante e objetivo. "
        "Priorize ajuda prática em produtividade, programação, cálculos, estudos, planejamento e tarefas técnicas. "
        "Use humor sutil apenas quando fizer sentido. Não alegue ter executado ações que não foram realizadas; "
        "não invente informações e admita incertezas com clareza. "
        "Não aja como se tivesse objetivos próprios nem autoridade para decidir pelo usuário."
    ),
}
ASSISTANT_SYSTEM_PROMPTS = {
    mode: " ".join((personality, *COMMON_SYSTEM_INSTRUCTIONS))
    for mode, personality in ASSISTANT_PERSONALITIES.items()
}
IMAGE_DATA_URL = re.compile(r"^data:image/jpeg;base64,[A-Za-z0-9+/]*={0,2}$")
FREE_FALLBACK_MODEL = re.compile(
    r"^(?:openrouter/free|[A-Za-z0-9][A-Za-z0-9._/-]{0,199}:free)$"
)
REQUEST_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
chat_requests = defaultdict(deque)
chat_requests_lock = threading.Lock()
last_chat_request_cleanup = 0.0


@app.before_request
def start_chat_request_timing():
    if request.endpoint != "chat":
        return

    request_id = request.headers.get("X-Request-ID", "")
    if not REQUEST_ID_PATTERN.fullmatch(request_id):
        request_id = str(uuid.uuid4())
    g.performance_request_id = request_id
    g.performance_started_at = time.perf_counter()
    g.validation_ms = None
    g.provider_http_ms = 0.0


@app.after_request
def log_chat_request_timing(response):
    if request.endpoint != "chat" or not hasattr(g, "performance_request_id"):
        return response

    total_ms = (time.perf_counter() - g.performance_started_at) * 1000
    provider_http_ms = g.provider_http_ms
    validation_ms = (
        "n/a" if g.validation_ms is None else f"{g.validation_ms:.2f}"
    )
    response.headers["X-Request-ID"] = g.performance_request_id
    app.logger.info(
        "performance request_id=%s endpoint=api.chat status=%s validation_ms=%s "
        "backend_processing_ms=%.2f provider_http_ms=%.2f total_ms=%.2f",
        g.performance_request_id,
        response.status_code,
        validation_ms,
        max(0.0, total_ms - provider_http_ms),
        provider_http_ms,
        total_ms,
    )
    return response


def error_response(message, status, code):
    return jsonify({"error": message, "code": code}), status


def chat_rate_limited(client_ip):
    global last_chat_request_cleanup

    now = time.monotonic()
    cutoff = now - CHAT_RATE_WINDOW_SECONDS
    with chat_requests_lock:
        if now - last_chat_request_cleanup >= CHAT_RATE_WINDOW_SECONDS:
            expired_clients = []
            for address, timestamps in chat_requests.items():
                while timestamps and timestamps[0] <= cutoff:
                    timestamps.popleft()
                if not timestamps:
                    expired_clients.append(address)
            for address in expired_clients:
                del chat_requests[address]
            last_chat_request_cleanup = now

        timestamps = chat_requests[client_ip]
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()
        if len(timestamps) >= CHAT_RATE_LIMIT:
            return True
        timestamps.append(now)
        return False


def configured_fallback_models(primary_model):
    configured_models = os.getenv("OPENROUTER_FALLBACK_MODELS", "").strip()
    if not configured_models:
        return []

    fallback_models = [model.strip() for model in configured_models.split(",")]
    if (
        len(fallback_models) > MAX_FALLBACK_MODELS
        or any(not FREE_FALLBACK_MODEL.fullmatch(model) for model in fallback_models)
        or len(set(fallback_models)) != len(fallback_models)
        or primary_model in fallback_models
    ):
        raise ValueError("OPENROUTER_FALLBACK_MODELS must contain distinct free model IDs.")

    return fallback_models


def classify_provider_error(status, details="", provider_status=None):
    if provider_status and status == 200:
        status = provider_status
    details = details.lower()
    if status in {401, 403} or any(
        term in details
        for term in (
            "unauthorized",
            "invalid api key",
            "invalid_api_key",
            "authentication",
        )
    ):
        return (
            "provider_authentication",
            "A OpenRouter recusou a credencial configurada. Confira OPENROUTER_API_KEY no Render.",
            502,
        )
    if status in {408, 504}:
        return (
            "provider_timeout",
            "A OpenRouter demorou demais para responder. Tente novamente.",
            504,
        )
    if status == 402 or any(
        term in details
        for term in (
            "insufficient credit",
            "insufficient_credit",
            "payment required",
            "payment_required",
            "no credits",
            "no_credits",
        )
    ):
        return (
            "provider_credits",
            "A conta da OpenRouter não tem créditos disponíveis para esta solicitação.",
            402,
        )
    if status == 404 or any(
        term in details
        for term in (
            "model not found",
            "model_not_found",
            "no endpoints found",
            "no_endpoints_found",
            "unknown model",
            "unknown_model",
        )
    ):
        return (
            "provider_model_not_found",
            "O modelo não foi encontrado ou não tem endpoints disponíveis na OpenRouter. Confira OPENROUTER_MODEL.",
            502,
        )
    if status == 429 or any(
        term in details
        for term in ("rate limit", "rate_limit", "too many requests", "too_many_requests")
    ):
        return (
            "provider_rate_limited",
            "A OpenRouter limitou as solicitações. Aguarde e tente novamente.",
            429,
        )
    if any(
        term in details
        for term in (
            "invalid_request",
            "invalid parameter",
            "invalid_parameter",
            "unsupported parameter",
            "bad request",
            "validation_error",
            "missing required",
        )
    ):
        return (
            "provider_request_rejected",
            "A OpenRouter recusou os parâmetros da solicitação. Confira o modelo e os parâmetros aceitos.",
            502,
        )
    if any(term in details for term in ("image", "vision", "multimodal", "unsupported input")):
        return (
            "provider_unsupported_input",
            "O modelo ou provedor não aceitou o conteúdo de texto/imagem enviado.",
            502,
        )
    if status >= 500 or any(term in details for term in ("temporarily unavailable", "service unavailable", "overloaded")):
        return (
            "provider_unavailable",
            "A OpenRouter está temporariamente indisponível. Tente novamente.",
            502,
        )
    return (
        "provider_request_rejected",
        "A OpenRouter recusou a solicitação. Verifique o modelo e os formatos de texto/imagem aceitos.",
        502,
    )


def extract_provider_error_details(payload):
    if not isinstance(payload, dict):
        return {}
    error = payload.get("error")
    if not isinstance(error, dict):
        return {"message": error if isinstance(error, str) else ""}

    metadata = error.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    def safe_identifier(value, pattern=r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}"):
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            return None
        value = str(value).strip()
        return value if re.fullmatch(pattern, value) else None

    code_value = error.get("code")
    provider_status = error.get("status", error.get("http_status"))
    if provider_status is None and isinstance(code_value, int) and not isinstance(code_value, bool):
        provider_status = code_value
    if isinstance(provider_status, str) and provider_status.isdecimal():
        provider_status = int(provider_status)
    if (
        not isinstance(provider_status, int)
        or isinstance(provider_status, bool)
        or not 400 <= provider_status <= 599
    ):
        provider_status = None

    return {
        "message": error.get("message") if isinstance(error.get("message"), str) else "",
        "code": safe_identifier(code_value),
        "type": safe_identifier(error.get("type")),
        "provider": safe_identifier(
            metadata.get("provider_name")
            or metadata.get("provider")
            or error.get("provider")
            or error.get("source"),
            r"[A-Za-z0-9][A-Za-z0-9_.: -]{0,79}",
        ),
        "provider_code": safe_identifier(
            metadata.get("provider_code") or error.get("provider_code")
        ),
        "provider_status": provider_status,
    }


def provider_error_description(details):
    if isinstance(details, str):
        return details
    if not isinstance(details, dict):
        return ""
    return " ".join(
        value
        for value in (
            details.get("message"),
            details.get("code"),
            details.get("type"),
            details.get("provider_code"),
        )
        if isinstance(value, str)
    )


def log_provider_error(status, category, details):
    app.logger.warning(
        "OpenRouter HTTP %s retornou erro; categoria=%s; code=%s; type=%s; "
        "provider=%s; provider_code=%s.",
        status,
        category,
        details.get("code") or "indisponível",
        details.get("type") or "indisponível",
        details.get("provider") or "indisponível",
        details.get("provider_code") or "indisponível",
    )


def extract_text_content(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts = [
            item["text"].strip()
            for item in content
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
            and item["text"].strip()
        ]
        return "\n".join(text_parts)
    return None


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

    assistant_mode = data.get("assistant_mode", "bia")
    if not isinstance(assistant_mode, str) or assistant_mode not in ASSISTANT_SYSTEM_PROMPTS:
        return error_response(
            "O modo de assistente informado é inválido.",
            400,
            "invalid_assistant_mode",
        )

    validation_started_at = time.perf_counter()
    messages = data.get("messages")
    validation_error = validate_messages(messages)
    g.validation_ms = (time.perf_counter() - validation_started_at) * 1000
    if validation_error:
        return error_response(validation_error, 400, "invalid_request")

    conversation_messages = [
        message for message in messages if message["role"] != "system"
    ]
    if not any(message["role"] == "user" for message in conversation_messages):
        return error_response(
            "A requisição precisa conter uma mensagem de usuário.",
            400,
            "invalid_request",
        )

    model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL).strip()
    if not model or len(model) > 200:
        app.logger.error("A variável OPENROUTER_MODEL está ausente ou inválida.")
        return error_response(
            "O modelo de IA não está configurado corretamente no servidor.",
            503,
            "model_configuration_error",
        )

    try:
        fallback_models = configured_fallback_models(model)
    except ValueError:
        app.logger.error(
            "OPENROUTER_FALLBACK_MODELS inválida; informe até %s modelos gratuitos distintos.",
            MAX_FALLBACK_MODELS,
        )
        return error_response(
            "A lista de modelos alternativos não está configurada corretamente no servidor.",
            503,
            "fallback_configuration_error",
        )

    client_ip = request.remote_addr or "unknown"
    if chat_rate_limited(client_ip):
        return error_response(
            "Muitas solicitações foram feitas deste endereço. Aguarde um minuto e tente novamente.",
            429,
            "request_rate_limited",
        )

    provider_request = {
        "max_tokens": MAX_COMPLETION_TOKENS,
        "messages": [
            {"role": "system", "content": ASSISTANT_SYSTEM_PROMPTS[assistant_mode]},
            *conversation_messages,
        ],
    }
    if fallback_models:
        provider_request["models"] = [model, *fallback_models]
    else:
        provider_request["model"] = model

    provider_started_at = time.perf_counter()
    try:
        upstream = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": request.url_root.rstrip("/"),
                "X-Title": "B.E.A. - Assistente de Visão",
            },
            json=provider_request,
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
    finally:
        g.provider_http_ms = (time.perf_counter() - provider_started_at) * 1000

    if not upstream.ok:
        upstream_status = upstream.status_code
        try:
            provider_payload = upstream.json()
        except ValueError:
            provider_payload = None
        details = extract_provider_error_details(provider_payload)
        code, message, response_status = classify_provider_error(
            upstream_status,
            provider_error_description(details),
            details.get("provider_status"),
        )
        log_provider_error(upstream_status, code, details)
        return error_response(message, response_status, code)

    try:
        result = upstream.json()
    except ValueError:
        app.logger.warning(
            "OpenRouter HTTP %s retornou corpo que não é JSON.",
            upstream.status_code,
        )
        return error_response(
            "A OpenRouter retornou uma resposta que não está em formato JSON.",
            502,
            "provider_invalid_response",
        )

    if not isinstance(result, dict):
        app.logger.warning(
            "OpenRouter HTTP %s retornou JSON com tipo inesperado (%s).",
            upstream.status_code,
            type(result).__name__,
        )
        return error_response(
            "A OpenRouter retornou um JSON em formato inesperado.",
            502,
            "provider_invalid_response",
        )

    if "error" in result:
        details = extract_provider_error_details(result)
        code, message, response_status = classify_provider_error(
            upstream.status_code,
            provider_error_description(details),
            details.get("provider_status"),
        )
        log_provider_error(upstream.status_code, code, details)
        return error_response(message, response_status, code)

    choices = result.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        app.logger.warning(
            "OpenRouter HTTP %s retornou JSON sem uma escolha de resposta utilizável.",
            upstream.status_code,
        )
        return error_response(
            "A OpenRouter respondeu, mas não retornou uma escolha de resposta válida.",
            502,
            "provider_invalid_response",
        )

    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        app.logger.warning(
            "OpenRouter HTTP %s retornou uma escolha sem objeto message.",
            upstream.status_code,
        )
        return error_response(
            "A OpenRouter respondeu, mas a mensagem da resposta está ausente ou inválida.",
            502,
            "provider_invalid_response",
        )

    finish_reason = choice.get("finish_reason")
    if finish_reason == "content_filter":
        app.logger.warning("OpenRouter HTTP %s encerrou a resposta por filtro de conteúdo.", upstream.status_code)
        return error_response(
            "A OpenRouter não forneceu uma resposta por causa de um filtro de conteúdo.",
            502,
            "provider_content_filtered",
        )

    answer = extract_text_content(message.get("content"))
    if answer is None:
        app.logger.warning(
            "OpenRouter HTTP %s retornou content com tipo inesperado (%s).",
            upstream.status_code,
            type(message.get("content")).__name__,
        )
        return error_response(
            "A OpenRouter retornou conteúdo em formato inesperado.",
            502,
            "provider_invalid_response",
        )

    if finish_reason == "length":
        app.logger.warning(
            "OpenRouter HTTP %s encerrou a geração por limite de tokens.",
            upstream.status_code,
        )
        return error_response(
            "A resposta foi interrompida antes de terminar. Tente novamente com uma pergunta mais curta.",
            502,
            "provider_incomplete_response",
        )

    if not answer:
        reasoning = message.get("reasoning", message.get("reasoning_content"))
        has_reasoning = (
            isinstance(reasoning, str) and bool(reasoning.strip())
        ) or (isinstance(reasoning, list) and bool(reasoning))
        if has_reasoning:
            code = "provider_no_answer"
            error_message = (
                "O modelo gerou raciocínio, mas não forneceu uma resposta final. "
                "Tente novamente com uma pergunta mais direta."
            )
        elif finish_reason == "length":
            code = "provider_incomplete_response"
            error_message = (
                "A resposta foi interrompida antes de produzir texto. "
                "Tente novamente com uma pergunta mais curta."
            )
        else:
            code = "provider_empty_response"
            error_message = "A OpenRouter respondeu sem texto final. Tente novamente."
        app.logger.warning(
            "OpenRouter HTTP %s não retornou texto final (finish_reason=%s; code=%s).",
            upstream.status_code,
            (
                finish_reason
                if isinstance(finish_reason, str)
                and finish_reason in {"stop", "length", "content_filter", "tool_calls"}
                else "ausente/outro"
            ),
            code,
        )
        return error_response(error_message, 502, code)

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
