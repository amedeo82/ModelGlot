# Piano di implementazione: ChatGPT Desktop e Codex Desktop

Status: proposed
Data: 2026-11-17
Analisi di riferimento: [`chatgpt-desktop-codex-desktop-integration-analysis.md`](chatgpt-desktop-codex-desktop-integration-analysis.md)
Obiettivo: qualificare e rendere ufficiale l'uso del workspace Codex locale della ChatGPT desktop app e del Codex client legacy attraverso FCC.

## 1. Principi di esecuzione

Il piano conserva l'architettura esistente: una sola integrazione, basata sulla Codex home
e sul file `config.toml`, serve Codex CLI, Codex IDE extension e Codex locale in ChatGPT
Desktop.

Non sono previsti:

- una seconda configurazione Codex;
- una card Admin separata per ChatGPT Desktop;
- il routing della modalità Chat standard;
- il supporto di Codex Cloud, ChatGPT Work cloud o Work Cloud;
- l'autenticazione cloud OpenAI tramite FCC;
- la modifica del contratto Responses già conforme.

Ogni step deve essere implementato in un branch o worktree separato, con test e rollback
indipendenti. La merge avviene solo dopo il rispetto dei criteri di accettazione dello step.

## 2. Stato degli step

| ID | Step | Priorità | Stato | Dipendenze | Deliverable |
| --- | --- | --- | --- | --- | --- |
| S01 | Qualificare la matrice dei client desktop | P0 | proposed | — | Matrice versionata e test report |
| S02 | Correggere naming, scope e copy Admin | P0 | proposed | S01 | UI e README coerenti |
| S03 | Aggiungere diagnostica config/catalogo/modello | P0 | proposed | S01 | Status avanzato senza segreti |
| S04 | Rendere conservative le capability del catalogo | P0 | proposed | S03 | Catalogo senza web search falso |
| S05 | Verificare il tool loop Responses | P0 | proposed | S03, S04 | Test live e smoke test |
| S06 | Gestire il riavvio e il refresh del client | P1 | proposed | S02, S05 | Refresh verificato end-to-end |
| S07 | Introdurre metadata di versione del catalogo | P1 | proposed | S04 | Schema versionato |
| S08 | Validare il catalogo per versione client | P1 | proposed | S07 | Validator e matrice compatibilità |
| S09 | Rilevare il Codex CLI bundled | P2 | proposed | S07 | Detection best-effort |
| S10 | Documentare sicurezza, troubleshooting e rollback | P0 | proposed | S03, S05, S06 | Runbook operativo |
| S11 | Eseguire la release qualification completa | P0 | proposed | S01–S10 | Report di rilascio |

## 3. Fase 0 — Preparazione e baseline

### S01 — Qualificare la matrice dei client desktop

**Obiettivo**

Stabilire quali versioni della ChatGPT desktop app e del Codex client legacy sono
supportate e riprodurre il comportamento reale.

**Attività**

1. Identificare le versioni disponibili per test su Windows, macOS e Linux.
2. Per ogni versione registrare:
   - sistema operativo e architettura;
   - versione ChatGPT desktop app;
   - versione del Codex CLI bundled, se rilevabile;
   - percorso della Codex home e presenza di `CODEX_HOME`;
   - modalità di installazione e presenza del binario;
   - comportamento di Connect, Refresh e Disconnect;
   - comparsa del provider FCC nel model picker;
   - completamento di una richiesta Responses;
   - esecuzione di un tool call;
   - comportamento al riavvio dell'app.
3. Ripetere il test nella configurazione Windows nativo.
4. Se WSL è disponibile, verificare separatamente la home Linux e documentare che non
   coincide con quella Windows.
5. Conservare gli screenshot e i log tecnici senza token, cookie o header di auth.
6. Classificare ogni client come:
   - `supported`;
   - `supported_with_limitations`;
   - `unsupported`;
   - `not_tested`.

**File coinvolti**

- `docs/chatgpt-desktop-codex-desktop-integration-analysis.md`;
- nuova sezione della stessa analisi o documento di test associato;
- `tests/manual/` solo se il repository adotta già test manuali versionati.

**Criteri di accettazione**

- La matrice identifica almeno una versione desktop realmente eseguita.
- Ogni combinazione ha un esito riproducibile.
- Le differenze tra CLI, IDE e desktop sono documentate.
- È esplicito quali superfici cloud restano fuori dallo scope.
- Nessun log contiene credenziali.

**Test**

- test manuale della matrice;
- confronto della configurazione generata con quella prevista;
- verifica che un token FCC non compaia nei log o in `config.toml`.

**Rollback**

Non richiede rollback del codice: la matrice è artefatto di qualificazione. Le
classificazioni non supportate non devono essere pubblicizzate.

**Stima**

1–2 giorni, dipendentemente dai dispositivi disponibili.

## 4. Fase 1 — Esperienza utente e stato

### S02 — Correggere naming, scope e copy Admin

**Obiettivo**

Chiarire che la card esistente copre la superficie Codex locale della ChatGPT desktop app,
senza creare una nuova integrazione.

**Attività**

1. Rinominare la card da “Codex in VS Code and App” a un titolo che includa:
   - Codex CLI;
   - Codex IDE extension;
   - ChatGPT Desktop (Codex locale).
2. Aggiungere una descrizione breve che distingua workspace Codex locale e funzioni cloud.
3. Mostrare i passaggi:
   - selezionare un modello FCC nel model picker;
   - riavviare o riaprire il client;
   - verificare che la sessione stia usando il provider FCC.
4. Aggiornare README, docs e test E2E che ricercano il vecchio titolo.
5. Evitare la promessa che la modalità Chat standard venga servita da FCC.

**File coinvolti**

- `src/free_claude_code/api/admin_static/index.html:143-152`;
- `README.md:36`;
- `README.md:452`;
- `e2e/test_admin_integrations.py:65-157`;
- test frontend esistenti per la card;
- `docs/chatgpt-desktop-codex-desktop-integration-analysis.md`.

**Criteri di accettazione**

- Il nome della nuova card elenca le tre superfici locali.
- Il testo identifica esplicitamente “Codex locale”.
- Il testo dichiara che Chat standard e le superfici cloud non usano FCC.
- I test E2E vengono aggiornati e verificano il nuovo copy.
- Nessun riferimento utente-visibile a “Codex App” resta ambiguo.

**Test**

- test unitari dei template, se presenti;
- test E2E della card;
- snapshot test, se adottati dal progetto;
- verifica responsive della nuova descrizione.

**Rollback**

Ripristinare il template Admin precedente. La modifica non modifica lo stato su disco.

**Stima**

1 giorno.

### S03 — Aggiungere diagnostica config/catalogo/modello

**Obiettivo**

Permettere all'utente di distinguere errori di configurazione, modello non selezionato e
client non supportato, senza esporre segreti.

**Attività**

1. Definire un DTO di status Codex con campi non sensibili:
   - `configured`;
   - `provider`;
   - `selected_model`;
   - `catalog_path`;
   - `catalog_available`;
   - `selected_model_available`;
   - `model_count`;
   - `supported_surfaces`;
   - `warnings`;
   - `last_refresh_at`, se il dato è già disponibile senza modificare lo schema.
2. Implementare la lettura del catalogo tramite il resolver esistente.
3. Confrontare il modello selezionato con gli alias del catalogo.
4. Aggiungere warning per:
   - catalogo assente o non leggibile;
   - modello top-level assente;
   - modello non presente nel catalogo FCC;
   - provider selezionato diverso da FCC;
   - versione client incompatibile quando già rilevata.
5. Esporre i dati nelle route Admin esistenti senza creare endpoint duplicati.
6. Redigere i test per verificare l'assenza di token, auth header e secret nei payload.

**File coinvolti**

- `src/free_claude_code/harnesses/codex_integration.py`;
- `src/free_claude_code/harnesses/codex_model_catalog.py`;
- `src/free_claude_code/config/paths.py:108-111`;
- `src/free_claude_code/runtime/integration_service.py:696-783`;
- `src/free_claude_code/api/admin_routes.py`, se necessario per il DTO;
- `src/free_claude_code/api/admin_static/index.html`;
- `tests/harnesses/test_codex_integration.py`;
- `tests/api/test_codex_integration_routes.py`.

**Criteri di accettazione**

- Lo status distingue le condizioni `catalog_available=false`, modello non selezionato e
  modello non presente.
- Il percorso del catalogo usa il resolver centralizzato.
- Nessun payload contiene il credential helper output o altri segreti.
- La UI mostra solo azioni pertinenti al problema rilevato.
- I test coprono configurazione valida, catalogo assente, modello esterno e errore di
  lettura.

**Test**

- unit test del resolver e del mapper;
- API test del contratto status;
- test di serializzazione per assenza di secret;
- test della UI per ciascuno stato.

**Rollback**

La feature diagnostica deve essere additive. Il rollback consiste nel nascondere i nuovi
campi senza rimuovere la logica di configurazione esistente.

**Stima**

1–2 giorni.

### S04 — Rendere conservative le capability del catalogo

**Obiettivo**

Non esporre al client Codex capacità che il provider upstream non implementa.

**Attività**

1. Introdurre un resolved model metadata nel catalogo provider.
2. Impostare `supports_search_tool = true` solo se il provider e il modello supportano
   esplicitamente Responses web search.
3. Includere `web_search_tool_type` solo per i modelli realmente supportati.
4. Nei modelli senza supporto, omettere il campo oppure usare un valore che non abiliti il
   tool.
5. Aggiungere test per un provider senza web search e uno con supporto.
6. Verificare che il model picker mostri le capability corrette e che non venga generato un
   tool non supportato.

**File coinvolti**

- `src/free_claude_code/harnesses/codex_model_catalog.py:82`;
- `src/free_claude_code/harnesses/codex_model_catalog.py:95`;
- modelli/capability del provider, se già esistenti;
- `tests/harnesses/test_codex_integration.py`;
- test del catalogo esistenti.

**Criteri di accettazione**

- Un modello senza supporto web search non dichiara `supports_search_tool = true`.
- `web_search_tool_type` non è emesso per modelli non supportati.
- Un modello supportato conserva il comportamento attuale.
- Il catalogo resta valido per il Codex client.

**Test**

- snapshot del catalogo;
- test parametrico delle capability;
- smoke test del tool loop con web search disabilitato;
- test del tool loop con web search abilitato, solo per un provider supportato.

**Rollback**

Ripristinare il generatore del catalogo precedente. La modifica deve essere isolata in un
commit per agevolare il rollback.

**Stima**

1 giorno.

## 5. Fase 2 — Validazione end-to-end

### S05 — Verificare il tool loop Responses

**Obiettivo**

Dimostrare che Codex locale usa correttamente FCC per testo, tool call e tool output.

**Attività**

1. Preparare una richiesta deterministica che richieda una tool.
2. Verificare la sequenza:
   - `response.output_item.done` con `function_call`;
   - `call_id` stabile;
   - richiesta successiva con `function_call_output`;
   - `response.completed`;
   - risposta finale senza loop infinito.
3. Verificare il replay del contesto senza `previous_response_id`.
4. Verificare che un errore del provider termini lo stream e mostri un errore utile.
5. Ripetere il test nei client locali supportati.
6. Catturare metriche senza payload sensibili.

**File coinvolti**

- `tests/api/test_openai_codex_compatibility.py`;
- `src/free_claude_code/core/openai_responses/provider_stream.py:105-109`;
- `src/free_claude_code/core/openai_responses/tool_calls.py:103-128`;
- `src/free_claude_code/core/openai_responses/messages_request.py:414-417`;
- `src/free_claude_code/core/openai_responses/native.py:50-52`.

**Criteri di accettazione**

- Il tool loop completa senza duplicare la chiamata.
- Il risultato della tool viene associato al `call_id` corretto.
- Il follow-up conserva il contesto utile.
- Lo stream ha un terminale univoco.
- Il test passa almeno su Codex CLI e ChatGPT Desktop, quando disponibili.

**Test**

- test API automatici;
- test live sul client;
- test di regressione sul tool loop esistente.

**Rollback**

La verifica non richiede rollback. Un fallimento blocca il rilascio dello scope desktop.

**Stima**

1–2 giorni.

### S06 — Gestire il riavvio e il refresh del client

**Obiettivo**

Garantire che Connect e Refresh producano una configurazione effettivamente applicata dal
client.

**Attività**

1. Verificare quando Codex ricarica `config.toml` e il catalogo.
2. Distinguere:
   - prima applicazione: riavvio dell'app/CLI;
   - refresh successivo: nuova sessione o riavvio, secondo il client;
   - modifica del catalogo: riavvio per ricaricare il model picker.
3. Aggiornare il messaggio UI con l'azione corretta per ciascun client.
4. Verificare che Refresh non duplichi chiavi TOML o voci di catalogo.
5. Verificare che Disconnect richieda anch'esso la riapertura del client quando la config
   è già stata caricata.
6. Coprire con test E2E il percorso Connect → Refresh → Disconnect.

**File coinvolti**

- `src/free_claude_code/harnesses/codex_integration.py:70-147`;
- `src/free_claude_code/runtime/integration_service.py:696-783`;
- `src/free_claude_code/api/admin_static/index.html`;
- `tests/harnesses/test_codex_integration.py:79-108`;
- `tests/api/test_codex_integration_routes.py`;
- `e2e/test_admin_integrations.py:65-157`.

**Criteri di accettazione**

- Refresh è idempotente.
- Il messaggio indica il riavvio necessario.
- Il test E2E copre l'intero lifecycle.
- Disconnect rimuove solo gli elementi FCC.

**Test**

- unit test di idempotenza;
- API test del lifecycle;
- E2E della card;
- test live del ricaricamento.

**Rollback**

Ripristinare il precedente copy del messaggio. La logica di idempotenza deve restare.

**Stima**

0,5–1 giorno.

## 6. Fase 3 — Robustezza del catalogo

### S07 — Introdurre metadata di versione del catalogo

**Obiettivo**

Rendere il catalogo evolvibile e diagnosticabile.

**Attività**

1. Definire una versione di schema, per esempio `catalog_schema_version = 1`.
2. Definire `minimum_codex_version` o una policy equivalente.
3. Conservare una versione minima del client supportato.
4. Aggiungere metadata senza rimuovere i campi attuali.
5. Scrivere una funzione di validazione del catalogo.
6. Fallire esplicitamente la generazione se un campo obbligatorio è invalido.
7. Aggiungere test di regressione per lo schema.

**File coinvolti**

- `src/free_claude_code/harnesses/codex_model_catalog.py:49-101`;
- `src/free_claude_code/harnesses/codex_integration.py`;
- test del catalogo;
- `tests/harnesses/test_codex_integration.py`.

**Criteri di accettazione**

- Il catalogo espone una versione di schema.
- La versione minima del client è leggibile e validabile.
- I test rilevano campi mancanti o tipi non validi.
- La generazione per i modelli correnti non cambia i campi richiesti dal client.

**Test**

- test di validazione;
- test di regressione dello schema;
- test di compatibilità con il Codex client.

**Rollback**

La feature deve essere opt-in durante l'introduzione e facilmente isolabile in un commit.

**Stima**

1 giorno.

### S08 — Validare il catalogo per versione client

**Obiettivo**

Garantire che la versione desktop del Codex client accetti il catalogo generato.

**Attività**

1. Identificare lo schema accettato dalle versioni supportate.
2. Implementare un validator che confronti:
   - schema del catalogo;
   - versione client;
   - alias;
   - campi obbligatori;
   - capability supportate.
3. Definire una policy di fallback conservativa per versioni non riconosciute.
4. Salvare un report di validazione nella diagnosi, senza segreti.
5. Aggiungere fixture per le versioni client note.

**File coinvolti**

- `src/free_claude_code/harnesses/codex_model_catalog.py`;
- `src/free_claude_code/harnesses/codex_integration.py`;
- nuovi fixture di test, se necessario;
- `tests/harnesses/test_codex_integration.py`.

**Criteri di accettazione**

- Una versione supportata e il suo schema passano la validazione.
- Una versione incompatibile produce un warning o un errore comprensibile.
- Il fallback non dichiara capability non verificate.
- Il report consente di riprodurre la diagnosi.

**Test**

- fixture per versione supportata;
- fixture per versione incompatibile;
- fixture per versione sconosciuta;
- test con catalogo modificato.

**Rollback**

La validazione può essere disabilitata tramite feature flag/configurazione interna senza
revertire il catalogo.

**Stima**

2–3 giorni.

### S09 — Rilevare il Codex CLI bundled

**Obiettivo**

Fornire un suggerimento accurato sulla versione client desktop, senza dipendere da path
specifici fragili.

**Attività**

1. Ricercare in modo best-effort il binario Codex associato alla desktop app.
2. Preferire metadati di installazione affidabili rispetto a una scansione ricorsiva del
   filesystem.
3. Eseguire il binario solo se è concesso e considerato attendibile.
4. Usare `--version` o un equivalente documentato per ottenere la versione.
5. Cache del risultato per sessione.
6. Fallire silenziosamente e registrare soltanto “versione non disponibile”.
7. Non fare della detection un prerequisito di Connect.

**File coinvolti**

- `src/free_claude_code/harnesses/codex_integration.py`;
- eventuale modulo OS-specifico vicino agli altri resolver;
- `tests/harnesses/test_codex_integration.py`.

**Criteri di accettazione**

- La detection non blocca mai Connect.
- Un risultato errato non configura path o parametri non sicuri.
- La versione è visualizzata solo quando nota.
- La detection copre almeno il caso Windows nativo della matrice.

**Test**

- test con binario fittizio;
- test con path inesistente;
- test con permesso di esecuzione negato;
- test in ambiente senza desktop app.

**Rollback**

La detection può essere disabilitata mantenendo il fallback manuale.

**Stima**

1–2 giorni.

## 7. Fase 4 — Operatività e rilascio

### S10 — Documentare sicurezza, troubleshooting e rollback

**Obiettivo**

Fornire una procedura completa per setup, diagnosi e ripristino.

**Attività**

1. Documentare la configurazione richiesta:
   - Codex home corretta;
   - `CODEX_HOME` quando si usa WSL o un'istanza separata;
   - provider FCC;
   - base URL;
   - credential helper;
   - catalogo locale.
2. Documentare i sintomi e la causa:
   - provider assente;
   - modello non selezionato;
   - catalogo non caricato;
   - client avviato prima di Connect;
   - proxy raggiungibile solo via host diverso;
   - tool non disponibile per capability.
3. Documentare il rollback manuale:
   - backup di `config.toml`;
   - Disconnect dalla UI;
   - verifica che il file non contenga più il provider FCC;
   - riavvio del client.
4. Raccomandare `HOST=127.0.0.1` oppure Proxy Authentication quando il proxy è in ascolto
   su tutte le interfacce.
5. Documentare che il credential helper evita di salvare il token nel TOML.
6. Aggiungere un runbook operativo e una sezione FAQ.

**File coinvolti**

- `README.md:118-122`;
- `README.md:452`;
- `docs/chatgpt-desktop-codex-desktop-integration-analysis.md`;
- `docs/architecture-analysis.md:185-189`;
- documentazione esistente per Codex integration, se presente.

**Criteri di accettazione**

- Il runbook copre setup, errori comuni, rollback e sicurezza.
- I comandi sono verificati sulla piattaforma di riferimento.
- La matrice delle superfici supportate è linkata.
- Il rollback non richiede conoscenze interne del codebase.

**Test**

- prova manuale della procedura su un ambiente pulito;
- verifica dei comandi e dei path;
- review da parte di un utente che non ha implementato la feature.

**Rollback**

Correzione editoriale; nessuna modifica runtime.

**Stima**

0,5–1 giorno.

### S11 — Release qualification completa

**Obiettivo**

Verificare che l'integrazione sia pronta per il rilascio e che non siano state introdotte
regressioni.

**Attività**

1. Eseguire l'intera suite del progetto.
2. Eseguire lint, typecheck e test secondo i comandi definiti dal repository.
3. Eseguire i test API, runtime, harness, CLI ed E2E pertinenti.
4. Ripetere la matrice live sui client supportati.
5. Verificare Connect → Refresh → Disconnect in un ambiente pulito.
6. Verificare che il file TOML non contenga token.
7. Verificare il binding loopback e l'autenticazione proxy.
8. Verificare il tool loop e il follow-up conversazionale.
9. Preparare le note di rilascio con supporto, limiti e problemi noti.

**Comandi di verifica**

La repository deve determinare i comandi canonici. Applicabili come baseline, senza
assumere che esistano:

```bash
pytest tests/harnesses/test_codex_integration.py
pytest tests/api/test_codex_integration_routes.py
pytest tests/api/test_openai_codex_compatibility.py
pytest e2e/test_admin_integrations.py
```

Devono inoltre essere eseguiti i comandi di lint e typecheck dichiarati nel `README.md`,
in `pyproject.toml` o in `AGENTS.md`, se presenti.

**Criteri di accettazione**

- Tutti i test automatici pertinenti passano.
- Lint e typecheck passano.
- La matrice live non presenta regressioni sui client dichiarati supportati.
- Nessun segreto compare nei file o nei log.
- Le note di rilascio indicano chiaramente i limiti Chat/Cloud.
- Il rollback è stato provato almeno una volta.

**Rollback**

La release viene bloccata se uno qualsiasi criterio fallisce. Dopo il merge, il rollback
consiste nel revert dei commit della feature e nel ripristino del catalogo precedente.

**Stima**

1 giorno.

## 8. Strategia di test

### Livello 1 — Unit test

Coprono:

- generazione e validazione del catalogo;
- capability conservative;
- parsing del TOML;
- merge e cleanup;
- mapping dello status;
- detection versione, quando implementata.

### Livello 2 — API e runtime

Coprono:

- status, connect, refresh e disconnect;
- idempotenza;
- errori e timeout;
- assenza di secret nelle risposte;
- compatibilità del contratto Responses.

### Livello 3 — E2E Admin

Coprono:

- nuova card e copy;
- azioni di setup e refresh;
- warning per modello/catalogo;
- percorso completo del lifecycle.

### Livello 4 — Live matrix

Copre:

- ChatGPT Desktop su Windows, macOS e Linux supportati;
- Codex CLI;
- Codex IDE extension;
- client legacy, se ancora impiegato;
- WSL come variante separata.

## 9. Rollback complessivo

Il rollback non richiede una migrazione dati. La procedura prevista è:

1. eseguire Disconnect dalla UI;
2. verificare la rimozione del provider FCC e del riferimento al catalogo;
3. ripristinare il backup di `config.toml`, se disponibile;
4. riavviare il client;
5. verificare il ripristino del provider/model precedente;
6. se necessario, ripristinare la versione precedente del proxy.

Il rollback deve preservare provider, modello, commenti e sezioni non FCC già presenti.

## 10. Metriche di completamento

Il progetto è completo quando:

- tutte le voci P0 sono `completed`;
- la matrice live copre almeno una versione ChatGPT Desktop per ciascun sistema operativo
  dichiarato supportato;
- non esistono capability web search dichiarate senza supporto;
- la UI identifica correttamente le tre superfici locali;
- i test automatici, lint e typecheck passano;
- il piano di rollback è verificato;
- la documentazione dichiara i limiti delle superfici cloud.

## 11. Sequenza di merge suggerita

1. S01 — matrice e qualificazione;
2. S03 — diagnostica;
3. S04 — capability conservative;
4. S02 — naming e copy;
5. S05 — tool loop;
6. S06 — lifecycle e refresh;
7. S10 — runbook;
8. S07–S09 — robustezza del catalogo;
9. S11 — release qualification.

In questo ordine la UI può essere aggiornata dopo che la diagnostica espone dati affidabili e
le capability conservative eliminano i falsi positivi prima della validazione end-to-end.
