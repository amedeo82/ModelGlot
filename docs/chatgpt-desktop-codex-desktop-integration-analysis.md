# Analisi di fattibilità: ChatGPT Desktop e Codex Desktop

Status: analisi completata; implementazione in corso
Data: 2026-11-17
Ambito: integrazione delle superfici desktop OpenAI con ModelGlot
Piano correlato: [`chatgpt-desktop-codex-desktop-integration-implementation-plan.md`](chatgpt-desktop-codex-desktop-integration-implementation-plan.md)

## 1. Sintesi

La fattibilità è alta per il workspace **Codex locale della ChatGPT desktop app** e per il
vecchio **Codex App/Codex Desktop**, perché entrambe le superfici leggono la configurazione
Codex locale e possono usare un provider Responses personalizzato.

ModelGlot ha già implementato la parte essenziale di questa integrazione:

- scrive un provider Codex locale in `~/.codex/config.toml`;
- usa il wire protocol OpenAI Responses;
- autentica il client tramite un credential helper;
- pubblica un catalogo locale dei modelli ModelGlot;
- conserva modello, commenti e altri provider dell'utente;
- espone Connect, Refresh e Disconnect dalla Admin UI.

Non è invece fattibile, tramite le API e i meccanismi di configurazione supportati, sostituire
il backend della modalità **Chat standard** della ChatGPT desktop app o quello delle
superfici cloud **ChatGPT Work**, **Codex Cloud** e **Work Cloud**. La configurazione
`model_provider`/`model_providers` documentata da OpenAI riguarda i client Codex locali e
non viene trasferita ai runtime cloud.

Il lavoro raccomandato non è quindi la creazione di una nuova integrazione duplicata, ma:

1. rendere esplicito che l'integrazione esistente copre Codex locale in ChatGPT Desktop;
2. aggiornare nomenclature e messaggi della UI;
3. verificare il comportamento con versioni desktop reali;
4. allineare il catalogo modelli allo schema del Codex client;
5. correggere le capability dichiarate indiscriminatamente nel catalogo;
6. aggiungere diagnostica non sensibile per distinguere configurazione presente, modello
   selezionato e client supportato.

## 2. Domanda e ambito

L'analisi distingue due direzioni spesso confuse.

### 2.1 ChatGPT/Codex come provider upstream di ModelGlot

ModelGlot può già usare:

- una sottoscrizione ChatGPT tramite OAuth;
- una API key OpenAI Platform;
- altri provider OpenAI-compatible.

Questo percorso riguarda `src/free_claude_code/providers/openai_codex/` e le impostazioni
OAuth. È indipendente dalla configurazione del client desktop OpenAI.

### 2.2 ChatGPT Desktop/Codex Desktop come client di ModelGlot

Questo percorso fa usare a un client desktop OpenAI i modelli e i provider esposti da ModelGlot.
La configurazione viene applicata a `config.toml` nella Codex home dell'utente ed è il
percorso oggetto di questo documento e del piano correlato.

## 3. Stato dei prodotti OpenAI

La documentazione OpenAI attuale descrive una singola **ChatGPT desktop app** disponibile
per macOS, Windows e Linux. La stessa applicazione offre diverse superfici, tra cui:

- Chat;
- ChatGPT Work;
- Codex locale;
- progetti, file e strumenti locali.

Il termine storico “Codex App” o “Codex Desktop” continua a essere usato nel progetto ModelGlot,
ma non rappresenta una terza integrazione separata. La superficie Codex desktop continua a
usare la Codex home locale:

- Windows: `%USERPROFILE%\.codex`;
- macOS/Linux: `~/.codex`, salvo un `CODEX_HOME` esplicito.

Su Windows la ChatGPT desktop app usa la stessa Codex home del Codex CLI nativo. Un CLI
eseguito dentro WSL usa invece la home Linux, a meno che non venga impostato `CODEX_HOME`.

Fonti:

- <https://learn.chatgpt.com/docs/app>
- <https://learn.chatgpt.com/docs/windows/windows-app>
- <https://learn.chatgpt.com/docs/auth>

## 4. Metodo ed evidenze

### 4.1 Analisi del repository

Sono stati esaminati:

- l'implementazione del provider e della configurazione Codex;
- il lifecycle Connect/Refresh/Disconnect;
- il servizio runtime delle integrazioni;
- la generazione del catalogo modelli;
- le API Admin e la UI;
- i test unitari, API, runtime, CLI ed E2E;
- la documentazione e il README del progetto.

### 4.2 Documentazione OpenAI

Sono state verificate:

- configurazione dei custom model provider;
- autenticazione command-backed;
- connessione di Codex a un gateway;
- contratto di compatibilità Responses API;
- rollout e qualificazione di un gateway;
- autenticazione della ChatGPT desktop app;
- percorso di configurazione su Windows.

Fonti:

- <https://learn.chatgpt.com/docs/config-file/config-advanced#custom-model-providers>
- <https://learn.chatgpt.com/docs/enterprise/connect-to-a-gateway>
- <https://learn.chatgpt.com/docs/enterprise/gateway-compatibility>
- <https://learn.chatgpt.com/docs/enterprise/roll-out-a-gateway>
- <https://learn.chatgpt.com/docs/config-file/config-reference>
- <https://learn.chatgpt.com/docs/auth>

### 4.3 Limiti della verifica

L'analisi non ha incluso:

- un test live della ChatGPT desktop app;
- una matrice di versioni desktop Windows/macOS/Linux;
- un test con il Codex CLI bundled nella desktop app;
- una verifica del comportamento delle funzioni cloud con un gateway locale;
- l'ispezione di bundle applicativi privati o di credenziali OpenAI.

Nell'ambiente di analisi non erano presenti né `codex` su `PATH` né un pacchetto ChatGPT/Codex
rilevabile, quindi non è stato possibile eseguire il test live.

## 5. Architettura ModelGlot attuale

### 5.1 Percorso di configurazione

La Codex home viene risolta in:

```python
Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
```

e il file configurato è `config.toml`.

Riferimenti:

- `src/free_claude_code/harnesses/codex_integration.py:21-23`;
- `src/free_claude_code/harnesses/codex_integration.py:238-243`.

La stessa configurazione è condivisa da:

- Codex CLI;
- estensione Codex per VS Code;
- Codex locale nella ChatGPT desktop app.

Non serve quindi una seconda card di integrazione per ChatGPT Desktop.

### 5.2 Provider ModelGlot

Il provider generato è:

```toml
model_provider = "modelglot"

[model_providers.modelglot]
name = "ModelGlot"
base_url = "http://127.0.0.1:16969/v1"
wire_api = "responses"
stream_idle_timeout_ms = 2147483647

[model_providers.modelglot.auth]
command = "modelglot-codex"
args = ["--print-proxy-auth-token"]
```

Riferimenti:

- `src/free_claude_code/harnesses/codex.py:35-49`;
- `src/free_claude_code/cli/launchers/codex.py:33-39`.

Il credential helper è compatibile con il contratto OpenAI: non riceve input su stdin e
scrive il token su stdout. Il launcher gestisce anche il flag interno
`--print-proxy-auth-token` prima di avviare Codex:

- `src/free_claude_code/cli/launchers/codex.py:42-46`.

### 5.3 Modello e catalogo

Connect non modifica il valore top-level `model`, ma imposta `model_provider = "modelglot"` e
aggiunge `model_catalog_json`. Il catalogo viene generato da:

- `src/free_claude_code/harnesses/codex_model_catalog.py:49-101`;
- `src/free_claude_code/config/paths.py:108-111`.

Il catalogo contiene alias, nomi visualizzati, livelli di reasoning, istruzioni base,
capacità di input, contesto, tool e ulteriori metadata necessari al model picker Codex.

### 5.4 Lifecycle

`codex_integration.configure()`:

- connette o verifica il provider;
- fa merge senza sovrascrivere provider, modello o commenti non ModelGlot;
- esegue refresh idempotente;
- rimuove esclusivamente gli elementi ModelGlot quando richiesto.

Riferimenti:

- `src/free_claude_code/harnesses/codex_integration.py:70-147`.

Il runtime coordina status, connect, disconnect e refresh:

- `src/free_claude_code/runtime/integration_service.py:696-783`.

La UI Admin espone già una card unica per VS Code e app desktop:

- `src/free_claude_code/api/admin_static/index.html:143-152`.

### 5.5 Copertura di test esistente

La configurazione Codex è protetta da test mirati:

- preservazione di modello, commenti e altri provider:
  `tests/harnesses/test_codex_integration.py:18-42`;
- refresh idempotente e preservazione dei retry:
  `tests/harnesses/test_codex_integration.py:79-108`;
- conflitto con un altro provider selezionato:
  `tests/harnesses/test_codex_integration.py:149-185`;
- API status/connect/disconnect:
  `tests/api/test_codex_integration_routes.py:27-50`;
- flusso E2E della card Admin:
  `e2e/test_admin_integrations.py:65-157`.

## 6. Contratto Codex gateway e conformità ModelGlot

OpenAI documenta i requisiti minimi di un gateway usato da Codex.

### 6.1 Endpoint e streaming

Il client deve usare `wire_api = "responses"` e il gateway deve accettare
`POST /v1/responses`, restituire SSE incrementali e terminare con `response.completed`.

ModelGlot espone il contratto Responses, gestisce gli eventi terminali e mantiene la
distinzione tra stream completato, incompleto e fallito:

- `src/free_claude_code/core/openai_responses/provider_stream.py:105-109`;
- `src/free_claude_code/core/openai_responses/tool_calls.py:103-128`;
- `src/free_claude_code/core/response_collection.py:107-110`.

### 6.2 Continuità

Un percorso HTTP stateless può continuare una conversazione riproponendo input, messaggi,
tool call e tool result. `previous_response_id` è necessario soltanto quando il trasporto
incrementale o WebSocket è attivo.

ModelGlot accetta `previous_response_id` nel modello di richiesta e lo rimuove prima del
chiamata upstream native, perché il proprio percorso usa input replayed:

- `src/free_claude_code/core/openai_responses/models.py:25`;
- `src/free_claude_code/core/openai_responses/messages_request.py:46-50`;
- `src/free_claude_code/core/openai_responses/native.py:50-52`.

Questa scelta è compatibile con il contratto documentato, purché il client rimandi la
conversazione completa.

### 6.3 Tool loop

Il gateway deve preservare `function_call`, `function_call_output`, `call_id` e la
corrispondenza tra chiamata e risultato.

ModelGlot riconosce e converte questi elementi:

- `src/free_claude_code/core/openai_responses/messages_request.py:414-417`;
- `src/free_claude_code/core/openai_responses/chat_request.py:104-122`;
- `src/free_claude_code/core/openai_responses/tool_adaptation.py:306-343`.

### 6.4 Autenticazione

ModelGlot utilizza un command-backed credential helper. Questo evita di scrivere il token del
proxy in `config.toml` e permette di ruotare il token senza modificare il file del client.

Il token è esposto soltanto al processo Codex che lo richiede. Le API Admin restano
loopback-only e i test verificano che il token non finisca nelle risposte Admin o nel
contenuto del TOML.

### 6.5 Catalogo

OpenAI richiede metadata coerenti con la versione del client per gli alias custom. ModelGlot
genera un catalogo locale, ma lo schema e le capability devono essere verificati contro
il Codex CLI incluso nella desktop app.

## 7. Matrice di fattibilità

| Superficie | Fattibilità | Stato ModelGlot | Conclusione |
| --- | --- | --- | --- |
| Codex CLI | Alta | Implementato e testato | Nessuna nuova integrazione necessaria |
| Codex IDE extension | Alta | Condivide `config.toml` | Validazione live utile |
| Codex locale in ChatGPT Desktop | Alta | Supporto implicito già presente | Consolidare e qualificare officially |
| Vecchio Codex App/Desktop | Alta | Stessa Codex home | Trattare come alias, non come nuova card |
| Chat standard in ChatGPT Desktop | Bassa | Nessun percorso supportato | Non promettere il routing ModelGlot |
| ChatGPT Work locale/Cloud | Bassa | Fuori dal contratto `model_provider` locale | Richiede una superficie client differente |
| Codex Cloud | Non supportata | Il provider custom non viene trasferito al cloud | Escludere |
| Backend ChatGPT hosted | Non fattibile | Richiederebbe comportamento privato | Escludere |

## 8. Gap e rischi

### 8.1 Naming obsoleto

La UI e il README usano ancora “Codex App”. La denominazione attuale è ChatGPT desktop app
con una superficie Codex locale. Il rischio è che l'utente non riconosca che la card già
copre il desktop.

### 8.2 Assenza di una validazione live

I test verificano configurazione, API e UI, ma non l'avvio reale della ChatGPT desktop app
né il tool loop nel suo processo.

### 8.3 Deriva dello schema del catalogo

OpenAI raccomanda di abbinare il catalogo alla versione del client, usando per le desktop
app la versione del CLI bundled. Il catalogo ModelGlot è costruito dal progetto e non registra
una versione minima o una matrice di compatibilità.

### 8.4 Capability eccessivamente generiche

Il catalogo dichiara attualmente:

- `web_search_tool_type = "text_and_image"`;
- `supports_search_tool = true`;

per ogni modello.

Riferimenti:

- `src/free_claude_code/harnesses/codex_model_catalog.py:82`;
- `src/free_claude_code/harnesses/codex_model_catalog.py:95`.

Non tutti i provider upstream supportano il web search Responses. Il catalogo non deve
pubblicare capacità che il provider non implementa.

### 8.5 Modello selezionato e provider selezionato

Connect imposta il provider ModelGlot ma conserva il modello precedente. Se il modello non
appartiene al catalogo ModelGlot, l'utente deve selezionare un modello ModelGlot dal picker. Lo stato
corrente non rende questa condizione esplicita.

### 8.6 Riavvio obbligatorio

Codex carica la configurazione e il catalogo all'avvio. Dopo Connect o Refresh l'app deve
essere riavviata o deve essere avviata una nuova sessione con la configurazione aggiornata.
Il messaggio esistente dice “Restart Codex”, ma non distingue l'app desktop.

### 8.7 Esposizione di rete del proxy

I default ModelGlot storici espongono il proxy su `0.0.0.0` senza autenticazione proxy. Anche se
il client usa `127.0.0.1`, il proxy può essere raggiungibile dalla rete locale.

Riferimenti:

- `README.md:118-122`;
- `docs/architecture-analysis.md:185-189`.

Prima di distribuire l'integrazione desktop è opportuno consigliare `HOST=127.0.0.1` oppure
l'attivazione della Proxy Authentication.

## 9. Design raccomandato

### 9.1 Un'unica integrazione Codex

Mantenere una sola integrazione basata sulla Codex home. La card Admin deve elencare tutte
le superfici locali supportate:

- Codex CLI;
- Codex IDE extension;
- Codex locale in ChatGPT Desktop.

Non creare una card separata per ChatGPT Desktop e non duplicare la configurazione.

### 9.2 Scope dichiarato

La documentazione e la UI devono indicare:

- ModelGlot sostituisce l'inferenza del workspace Codex locale;
- Chat standard, Work Cloud e Codex Cloud restano servizi OpenAI e non vengono instradati
  attraverso ModelGlot;
- l'utente deve selezionare un modello ModelGlot e riavviare il client.

### 9.3 Diagnostica non sensibile

Lo status dell'integrazione può aggiungere dati come:

- `provider`;
- `selected_model`;
- `catalog_path` già presente nelle paths;
- `catalog_available`;
- `selected_model_available`;
- `supported_surfaces`;
- `client_version`, quando rilevabile senza eseguire codice non fidato;
- `warnings` non contenenti segreti.

La detection dell'app installata deve essere best-effort e non deve impedire Connect su
un client CLI o IDE valido.

### 9.4 Catalogo version-aware

Il catalogo deve avere:

- una versione di schema interna;
- una versione minima Codex supportata;
- una matrice dei client desktop testati;
- test del contratto per i campi obbligatori;
- capability derivate dai metadata reali del provider.

La detection della versione bundled non deve essere l'unico meccanismo: il fallback deve
essere conservativo e documentato.

### 9.5 Capability conservative

Fino a quando il catalogo provider non espone una capability esplicita per Responses web
search, il catalogo Codex deve:

- non dichiarare `supports_search_tool = true` per default;
- omettere `web_search_tool_type`, oppure marcarlo in modo da non esporre il tool.

Il web search deve essere abilitato soltanto per provider che ne dichiarano il supporto e
superano il test del tool loop.

## 10. Piano di adozione raccomandato

### Fase 1 — Qualificazione minima

- stabilire la matrice delle versioni desktop supportate;
- rinominare la card e la documentazione;
- chiarire il limite Chat/Work/Cloud;
- aggiungere diagnostica di modello e catalogo;
- rendere conservative le capability del catalogo;
- eseguire il test live Windows/macOS.

### Fase 2 — Robustezza

- introdurre metadata di versione del catalogo;
- rilevare la versione del Codex CLI bundled quando possibile;
- validare il catalogo contro lo schema della versione client;
- aggiungere un test smoke automatizzato del percorso Responses;
- documentare rollback e troubleshooting.

### Fase 3 — Estensioni opzionali

- remote catalog endpoint conforme al formato Codex;
- distribuzione managed di `config.toml`/provider;
- supporto di profili Codex separati;
- integrazione con Codex App Server per esperienze embedded.

Le tre fasi non abilitano il routing della modalità Chat standard. Questo resta un non-obiettivo
salvo introduzione di un'API supportata da OpenAI.

## 11. Stima

| Attività | Stima |
| --- | ---: |
| Matrice live e decisioni di compatibilità | 1–2 giorni |
| Naming, copy e flusso Admin | 1 giorno |
| Diagnostica config/catalogo/modello | 1–2 giorni |
| Capability e catalogo version-aware | 2–4 giorni |
| Smoke test e matrice manuale | 1–2 giorni |
| Documentazione, review e release | 0,5–1 giorno |
| Totale prima release solida | 6,5–12 giorni |

La prima release può essere ridotta a circa 2–5 giorni se include naming, diagnostica
essenziale, capability conservative e una validazione live limitata. Lo schema
completamente version-aware richiede il percorso più lungo.

## 12. Criteri di successo

L'integrazione è considerata solida quando:

- la card Admin identifica chiaramente ChatGPT Desktop, VS Code e CLI;
- il testo chiarisce che è supportato solo il workspace Codex locale;
- Connect produce una configurazione valida per la Codex home condivisa;
- il model picker mostra i modelli ModelGlot senza metadata capacità falsi;
- un tool call locale viene completato in ChatGPT Desktop;
- un follow-up conserva il contesto;
- lo stream termina correttamente e non si blocca;
- Disconnect rimuove soltanto gli elementi ModelGlot;
- la matrice registra app, sistema operativo e versione Codex bundled;
- il proxy è raggiungibile soltanto dal loopback oppure protetto da autenticazione.

## 13. Conclusione

L'integrazione richiesta è tecnicamente sostenibile e in gran parte già presente. La
conclusione corretta non è “aggiungere ChatGPT Desktop e Codex Desktop come due nuovi
client”, ma “rendere ufficiale e qualificato il supporto Codex locale della ChatGPT desktop
app attraverso l'integrazione Codex condivisa già esistente”.

La modalità Chat standard e le superfici cloud restano fuori dallo scope supportato.
