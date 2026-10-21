# B.E.A. — Assistente de Visão

A B.E.A. é uma aplicação de acessibilidade que combina câmera, interação por voz e respostas de IA. O navegador envia as perguntas e imagens ao backend Flask; o backend acessa a OpenRouter usando uma chave mantida no servidor.

## Como funciona

- Depois de uma ativação inicial e da concessão das permissões, a escuta de voz fica contínua. Diga **“Bia”** antes do pedido para evitar que conversas ambientes sejam enviadas por engano.
- A B.E.A. pausa o reconhecimento enquanto processa uma solicitação ou reproduz áudio e o retoma ao terminar.
- O botão **Silenciar/Reativar microfone** controla a escuta. Silenciar não interrompe uma resposta que já esteja sendo reproduzida.
- Com a câmera disponível, a aplicação envia uma imagem para análise inicialmente após 15 segundos e, depois, a cada 60 segundos. A leitura automática pausa quando a página fica oculta ou a câmera deixa de estar disponível.
- A interface continua aceitando perguntas sobre o que está diante da câmera. Sem câmera, perguntas de voz podem seguir sem imagem.

## Requisitos

- Windows 10/11 e Python 3.10 ou superior.
- Uma chave da OpenRouter com acesso a um modelo que aceite imagens.
- Navegador compatível com `getUserMedia`, `SpeechRecognition`/`webkitSpeechRecognition` e síntese de voz. O Google Chrome é recomendado; os recursos disponíveis variam por navegador e dispositivo.
- HTTPS para hospedagem pública. Em desenvolvimento local, `localhost` é considerado contexto seguro pelos navegadores modernos.

## Instalação e execução local

Abra o PowerShell na pasta do projeto e execute:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
.\.venv\Scripts\python.exe app.py
```

No `.env`, configure `OPENROUTER_API_KEY` com sua chave. Não publique nem compartilhe esse arquivo. A variável `OPENROUTER_MODEL` pode ser configurada com o identificador de um modelo disponível que aceite texto e imagens; se omitida, é usado o modelo padrão do projeto. Opcionalmente, `OPENROUTER_FALLBACK_MODELS` aceita até três IDs gratuitos separados por vírgulas (sufixo `:free` ou `openrouter/free`). Se configurada, a OpenRouter tenta esses modelos na ordem após o principal; sem ela, o comportamento atual permanece.

Abra <http://127.0.0.1:5000>, conceda as permissões de câmera e microfone e toque uma vez em **Ativar B.E.A.**. Essa ativação inicial é necessária para iniciar os recursos protegidos pelo navegador e liberar a reprodução de áudio. Depois, use a palavra de ativação ou o botão de microfone.

O endpoint <http://127.0.0.1:5000/api/health> informa se o backend responde e se as variáveis de integração estão configuradas; ele não faz uma chamada à OpenRouter.

## Testes

Com as dependências da aplicação instaladas, execute a suíte com o `unittest` da biblioteca padrão:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Diagnóstico de desempenho

Durante uma solicitação, o console do navegador registra `capture_prepare`, `api_round_trip` e `response_to_voice_start`, com duração em milissegundos e um ID de requisição. O evento de início da voz informa `observed: false` quando o navegador não fornece um evento de início de fala mensurável.

O log do backend com a mesma ID registra `validation_ms`, `provider_http_ms`, `backend_processing_ms` e `total_ms`. `backend_processing_ms` é o tempo total da rota menos a chamada HTTP à OpenRouter; `validation_ms` mede a validação das mensagens. `api_round_trip` inclui serialização/envio, processamento do servidor, resposta e transporte. A diferença entre esse valor e `total_ms` é apenas uma estimativa de transporte e trabalho fora da rota, não uma medição isolada da rede.

Os logs registram somente ID, etapa, status e durações; não incluem perguntas, respostas, imagens nem credenciais. Use a ID para correlacionar o console do navegador aos logs do servidor.

## Mascote BIA

A interface contém um **placeholder técnico**, não a arte oficial final. Ele é um SVG inline organizado em grupos (`bia-head`, `bia-torso`, `bia-arms` e partes faciais) para permitir animações independentes sem dependências adicionais. Essa condição é indicada no texto acessível da mascote, sem um aviso visual adicional.

Ao preparar a arte definitiva, forneça um SVG original com camadas nomeadas para cabeça/cabelo, tronco, braços/mãos, olhos, sobrancelhas e boca (formas fechada e aberta). Substitua os desenhos dentro de `#biaMascot` preservando seu ID, os IDs/classes internos usados pelos seletores de animação, a viewBox e a indicação acessível de que a ilustração representa a BIA. Não incorpore uma imagem raster única se a animação facial e corporal continuar necessária.

As expressões seguem os estados reais do app. A boca começa e para com os eventos da `speechSynthesis`; se o navegador enviar limites de palavras, eles selecionam poses visuais simples a partir do início da palavra. Sem esses eventos, há apenas um movimento suave enquanto a fala está efetivamente ativa. Isso não é sincronização fonética. Piscadas e olhares usam temporizadores espaçados e variáveis, gestos acontecem somente durante a fala, e as animações respeitam `prefers-reduced-motion` e a visibilidade da página.

## Hospedagem no Render

Crie um **Web Service** conectado ao repositório e configure:

| Configuração | Valor |
|---|---|
| Runtime | Python |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app --bind 0.0.0.0:$PORT --timeout 60` |

Em **Environment Variables**, defina:

| Variável | Valor |
|---|---|
| `OPENROUTER_API_KEY` | Chave privada da OpenRouter, configurada somente no Render |
| `OPENROUTER_MODEL` | ID de um modelo disponível com suporte a texto e imagem |
| `OPENROUTER_FALLBACK_MODELS` | Opcional: até três IDs gratuitos, separados por vírgulas; use apenas modelos compatíveis com imagem |

O endpoint `/` serve a interface `index1.html`. Após o deploy, verifique `/api/health` e teste uma pergunta na interface. Não inclua `.env` no repositório.

## Limitações conhecidas

- A Web Speech API não está disponível em todos os navegadores. Alguns navegadores dependem de conexão à internet para reconhecimento de voz.
- O início de câmera, microfone e áudio depende das permissões e das políticas de ativação do navegador. Em caso de permissão negada ou recurso indisponível, a interface informa o problema; habilite a permissão e recarregue a página quando necessário.
- A leitura automática é periódica, não contínua em tempo real: usa aproximadamente uma chamada de IA por minuto enquanto a página está visível e a câmera está disponível. Isso consome dados, bateria e uso/créditos do provedor. Ela não roda em segundo plano.
- Qualidade e gênero percebido da voz sintetizada dependem das vozes instaladas/disponibilizadas pelo sistema e pelo navegador.
- O plano gratuito do Render pode suspender o serviço após inatividade e está sujeito aos limites do provedor e da plataforma.
- O limite de solicitações do backend é mantido em memória por processo; não equivale a um limite global entre múltiplas instâncias.

## Segurança

- A chave da OpenRouter é lida pelo backend através de variável de ambiente e nunca deve ser colocada no HTML, JavaScript ou mensagens de erro.
- `.env`, ambientes virtuais e caches devem permanecer fora do Git.
- Se uma chave tiver sido exposta em código ou histórico, revogue-a na OpenRouter e configure uma nova. Apagar o valor do arquivo atual não invalida cópias anteriores.
