# B.E.A. — Assistente de Visão

Aplicação local de acessibilidade com câmera, reconhecimento e síntese de voz e respostas de IA. O navegador envia as mensagens ao backend Flask; somente o backend acessa a OpenRouter.

## Requisitos

- Windows 10/11 e Python 3.10 ou superior.
- Chave da OpenRouter com acesso a um modelo compatível com imagens.
- Google Chrome recomendado para reconhecimento de voz em português.

## Configuração e execução

No PowerShell, na pasta do projeto:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
.\.venv\Scripts\python.exe app.py
```

No arquivo `.env`, substitua `replace-with-your-openrouter-api-key` pela chave nova da OpenRouter. Opcionalmente, altere `OPENROUTER_MODEL` para outro modelo compatível com entrada de imagens. Nunca coloque a chave no HTML, no JavaScript ou em arquivos versionados.

Abra `http://127.0.0.1:5000` no Chrome. O localhost permite acesso à câmera em navegadores compatíveis; aceite as permissões de câmera e microfone. O reconhecimento de voz pode depender da internet e do suporte do navegador.

Para conferir se o backend iniciou, acesse `http://127.0.0.1:5000/api/health`. A resposta indica apenas se a chave está configurada, sem expor seu conteúdo.

Para executar os testes locais do backend:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Hospedagem gratuita no Render

1. Envie o projeto para o GitHub, incluindo `app.py`, `index1.html`, `requirements.txt` e os demais arquivos necessários. Não envie `.env`.
2. No Render, crie um **Web Service** conectado ao repositório.
3. Configure:
   - **Runtime:** Python
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT`
4. Em **Environment Variables**, configure `OPENROUTER_API_KEY` com uma chave válida. Opcionalmente, configure `OPENROUTER_MODEL` com um modelo compatível com imagens.
5. Implante o serviço e abra a URL HTTPS fornecida pelo Render.

O comando `gunicorn app:app` carrega a aplicação WSGI `app` definida em `app.py`; o comando de inicialização acima também vincula o servidor ao host e à porta exigidos pelo Render. A rota `/` serve `index1.html`.

O plano gratuito pode suspender serviços inativos e ter limites de uso. Câmera e microfone dependem da permissão do navegador e de acesso HTTPS; reconhecimento de voz e vozes disponíveis variam conforme o navegador e o dispositivo.

## Segurança

- `.env` e ambientes virtuais são ignorados pelo Git.
- Se uma chave anterior foi colocada no código ou em um commit, revogue-a na OpenRouter e configure uma chave nova no `.env`. Remover a chave do arquivo atual não invalida cópias anteriores.
- Não publique o `.env` nem envie a chave para o navegador.