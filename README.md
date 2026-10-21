# B.E.A. — Assistente de Visão

A B.E.A. é uma aplicação de acessibilidade que combina câmera, interação por voz e respostas de IA. O navegador envia as perguntas e imagens ao backend Flask; o backend acessa a OpenRouter usando uma chave mantida no servidor.

## Como funciona

- Depois da ativação inicial e da concessão das permissões, o reconhecimento de fala fica ativo e aguarda a palavra do modo selecionado: **“Bia”** no modo BIA ou **“JARVIS”** no modo JARVIS. A captura depende de o navegador suportar reconhecimento de fala e das permissões concedidas.
- A B.E.A. pausa o reconhecimento enquanto processa uma solicitação ou reproduz áudio e o retoma ao terminar.
- O botão **Silenciar/Reativar microfone** controla a escuta. Silenciar não interrompe uma resposta que já esteja sendo reproduzida.
- O botão discreto **Ativar JARVIS/Voltar para BIA** alterna o tema visual e seleciona personalidade e perfil de voz para as próximas respostas; câmera, microfone e reconhecimento de fala permanecem compartilhados.
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

Abra <http://127.0.0.1:5000>, escolha o modo, conceda as permissões solicitadas para câmera e microfone e toque em **Ativar BIA** ou **Ativar JARVIS** conforme o modo. Essa ativação é necessária para iniciar os recursos protegidos pelo navegador e liberar a reprodução de áudio. Depois, diga a palavra de ativação correspondente ou use o controle de microfone.

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

As expressões seguem os estados reais do app. A boca começa e para com os eventos da `speechSynthesis`; quando o navegador fornece limites de palavras, as vogais da palavra selecionam poses visuais aproximadas. Sem esses eventos, uma sequência temporizada de poses por palavra e pausas é usada apenas enquanto a fala está ativa. Como `speechSynthesis` não expõe o áudio reproduzido para análise de amplitude, isso não é sincronização fonética. Olhos, sobrancelhas, cabeça, tronco e braços têm movimentos coordenados; piscadas, olhares e microreações variam em intervalos não fixos, e a atividade é suspensa com a página oculta ou movimento reduzido.

A personalidade é selecionada no backend a partir do modo ativo (`bia` ou `jarvis`), validado em cada solicitação. O prompt de sistema é mantido no servidor; instruções de sistema enviadas pelo navegador são ignoradas. A BIA mantém seu tom acolhedor e atento. JARVIS usa uma apresentação profissional, calma, precisa e objetiva, com foco em produtividade e tarefas técnicas. Ambos compartilham as orientações de idioma, precisão e segurança. A síntese de voz existente lê as respostas. Atualmente, cada requisição contém o contexto de sistema e a interação atual, sem histórico de conversa persistido.

A voz é selecionada entre as vozes em português disponibilizadas pelo navegador e pelo sistema. BIA mantém a preferência feminina já usada pela aplicação. JARVIS prioriza uma voz cujo nome indique uma opção masculina; se não houver correspondência identificável, usa a seleção usual em português da BIA para preservar a fala. Se o navegador não listar vozes em português, a fala mantém o idioma `pt-BR` e pode usar a voz padrão do navegador. A voz e o modo são fixados por resposta, mesmo se houver alternância enquanto uma chamada ou fala estiver em andamento. A disponibilidade e o gênero percebido variam por dispositivo e não podem ser garantidos pela Web Speech API.

O modo JARVIS exibe uma mascote masculina original em SVG dentro do mesmo palco da BIA. Cada ilustração mantém uma identidade visual própria, mas compartilha o estado de fala e os eventos de piscada; as poses da boca continuam aproximadas e usam os limites de fala ou a sequência de fallback já existentes.

## Modo visual JARVIS

A interface inicia no modo BIA e permite alternar entre `bia` e `jarvis` pelo botão no cabeçalho, sem recarregar a página. O modo é representado por `data-assistant-mode` no elemento principal e no `body`, centralizado pela função `setAssistantMode`, e é enviado ao backend nas novas solicitações. O botão de inicialização, as instruções, os status e as palavras de ativação seguem o modo selecionado: BIA reconhece “Bia” e suas variantes existentes; JARVIS reconhece “JARVIS” e variantes fonéticas comuns. Resultados de fala são interpretados com o modo ativo no momento do reconhecimento. O tema JARVIS usa fundo azul-marinho, painéis translúcidos, contornos e detalhes ciano, mantendo as informações reais de estado da câmera e do sistema. Alternar o modo atualiza os textos sem reiniciar câmera ou reconhecimento.

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
