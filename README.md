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

## Segurança

- `.env` e ambientes virtuais são ignorados pelo Git.
- Se uma chave anterior foi colocada no código ou em um commit, revogue-a na OpenRouter e configure uma chave nova no `.env`. Remover a chave do arquivo atual não invalida cópias anteriores.
- Não publique o `.env` nem envie a chave para o navegador.