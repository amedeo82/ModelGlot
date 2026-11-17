# Profilo FCC per Claude Desktop

Status: implementato
Data: 2026-11-17
Ambito: profilo gateway FCC per Claude Desktop in modalità third-party (3P)

## Sintesi

Free Claude Code (FCC) gestisce per Claude Desktop un profilo 3P dedicato, atomico e
conservativo. Il profilo instrada l'inferenza attraverso il gateway locale FCC, abilita la
scoperta dei modelli e conserva le personalizzazioni dell'utente.

Le migliorie principali rispetto alla prima integrazione sono:

- preferenza per il contesto da 1M token e metadati `supports_1m` nella vista Desktop;
- registrazione dei marketplace ufficiali Anthropic per plugin e skill;
- continuità della connessione quando Claude Desktop sigilla la chiave del gateway;
- conservazione degli override dei modelli e delle altre impostazioni del profilo;
- accesso di rete per gli strumenti Desktop configurato senza sovrascrivere le policy
  personalizzate;
- refresh idempotente e disconnessione riprendibile dopo un'interruzione.

Il profilo viene creato e applicato da
`src/free_claude_code/harnesses/claude_desktop_integration.py`. La sua vista dedicata del
catalogo è implementata in `src/free_claude_code/api/model_catalog.py` e selezionata tramite
l'header `X-FCC-Model-View: claude-desktop`.

## Configurazione del profilo

Oltre ai campi gateway e alla scoperta dei modelli, FCC gestisce questi valori:

```json
{
  "inferenceProvider": "gateway",
  "inferenceGatewayBaseUrl": "http://127.0.0.1:8082",
  "inferenceCredentialKind": "static",
  "inferenceGatewayApiKey": "<proxy-token>",
  "inferenceGatewayAuthScheme": "bearer",
  "modelDiscoveryEnabled": true,
  "modelPrefer1mContext": true,
  "inferenceCustomHeaders": {
    "X-FCC-Model-View": "claude-desktop"
  },
  "coworkEgressAllowedHosts": ["*"]
}
```

L'URL del gateway può usare HTTPS oppure HTTP solo verso `localhost`, `127.0.0.1` o `::1`.
La chiave mostrata sopra rappresenta il valore iniziale: Claude Desktop può sostituirlo con
una copia sigillata `__sealed__:...`.

Il profilo usa un UUID deterministico e l'header `X-FCC-Model-View` come marcatori di
proprietà. FCC rifiuta di sovrascrivere un profilo nativo che occupi accidentalmente lo
stesso UUID.

## Migliorie implementate

### Contesto da 1M token

`modelPrefer1mContext: true` fa preferire a Claude Desktop la variante da un milione di
token per i modelli compatibili. La discovery espone `supports_1m: true` nella sola vista
Desktop quando il catalogo del provider dichiara una finestra di almeno 1.000.000 token.

La preferenza non estende la capacità del provider. Il modello finale deve accettare la
richiesta e il percorso di traduzione deve inoltrare l'header beta `context-1m-2025-08-07`
quando richiesto dal client. La vista CLI non cambia.

Dettagli e fonti: [`claude-desktop-1m-context-and-official-marketplace.md`](claude-desktop-1m-context-and-official-marketplace.md).

### Marketplace ufficiali Anthropic

Il profilo registra i marketplace:

- `anthropics/claude-plugins-official`;
- `anthropics/knowledge-work-plugins`.

Sono configurati con `installationPreference: "available"`, quindi vengono resi disponibili
nella scheda **Customize → Plugins → Discover → Organization** senza installare
automaticamente tutti i plugin. Il refresh garantisce la presenza dei due marketplace
ufficiali, conserva i marketplace aggiuntivi e non sostituisce la configurazione
personalizzata di un marketplace ufficiale già presente.

La sincronizzazione periodica del marketplace ricalcola il contenuto del repository
ufficiale. Non trasferisce l'inventario dei plugin installati, delle skill salvate, dei
connector o degli accessi OAuth dall'account Claude.ai.

### Import Claude.ai — capability verificata, non ancora attivata

Claude Desktop in modalità 3P supporta un import one-shot dall'account Claude.ai
attraverso la chiave `claudeAiImport`. FCC non imposta ancora questa chiave: il pulsante
**Import…** in **Settings → Import & export** resta quindi disabilitato quando
l'import non è abilitato da un'altra fonte di configurazione.

La configurazione minima prevista per un'attivazione esplicita è:

```json
{
  "claudeAiImport": {
    "enabled": true,
    "bannerBehavior": "detect"
  }
}
```

L'import può copiare chat, progetti e artefatti dell'utente. Ogni import è una copia
one-shot: nuove attività nell'account non compaiono automaticamente. Non trasferisce
plugin personali, connector, estensioni desktop o token OAuth. Il piano di
implementazione FCC, le allowlist per organizzazione, la gestione di
`automatic3pImport` e i test sono descritti in
[`claude-desktop-1m-context-and-official-marketplace.md`](claude-desktop-1m-context-and-official-marketplace.md#sincronizzazione-con-laccount-claudeai).

### Continuità con chiave sigillata

Claude Desktop può crittografare in-place `inferenceGatewayApiKey`, sostituendo il token
FCC con un valore `__sealed__:...`. FCC conserva uno SHA-256 del token nell'archivio locale
`~/.fcc/claude-desktop-token.json`; non vi viene salvato il token in chiaro.

Una chiave sigillata viene considerata corrente quando il fingerprint corrisponde al token
FCC attivo. In questo caso il refresh non riscrive la chiave e l'integrazione resta
connessa. Se il fingerprint manca, è corrotto o corrisponde a un token precedente, FCC
considera il profilo obsoleto e scrive il token corrente, che Desktop potrà sigillare di
nuovo. Il fingerprint viene rimosso durante il Disconnect.

### Conservazione delle personalizzazioni

Connect, Reconnect e refresh aggiornano soltanto i campi gestiti da FCC. Sono preservati:

- `inferenceModels`, inclusi ordine, nomi e metadati per modello;
- override dei modelli salvati dall'utente;
- header personalizzati;
- marketplace aggiuntivi e configurazioni personalizzate dei marketplace ufficiali;
- policy di egress esistenti, inclusa una lista vuota o ristretta.

Se `coworkEgressAllowedHosts` non è presente, FCC imposta `["*"]` per consentire a Cowork,
Code e agli altri strumenti Desktop di raggiungere i servizi necessari. Una policy già
definita non viene modificata.

### Scritture conservative e riprendibili

Le configurazioni JSON vengono scritte in modo atomico e solo quando il valore desiderato
differisce da quello corrente. Connect e refresh sono quindi idempotenti e non producono
modifiche o notifiche inutili.

Prima di modificare Claude Desktop, il Disconnect salva un record locale senza credenziali in
`~/.fcc/claude-desktop-disconnect.json`. Se la pulizia viene interrotta, il record mantiene
l'operazione in uno stato `disconnect_pending`; l'Admin UI consente di ripeterla dopo un
reload o un riavvio. Una nuova operazione di Connect viene bloccata finché la pulizia non
è completa.

## Percorso dei file

La configurazione 3P usa una radice separata da quella standard di Claude Desktop:

| Piattaforma | Radice |
| --- | --- |
| Windows | `%LOCALAPPDATA%\Claude-3p` |
| macOS | `~/Library/Application Support/Claude-3p` |
| Linux | `${XDG_CONFIG_HOME:-~/.config}/Claude-3p` |

La struttura gestita contiene:

```text
<Claude-3p>/
├── configLibrary/
│   ├── <FCC_ID>.json
│   ├── <DEFAULT_ID>.json
│   └── _meta.json
└── claude_desktop_config.json
```

Gli archivi locali FCC usati per la ripresa della disconnessione e per il fingerprint
sono invece mantenuti in `~/.fcc/`.

## Ciclo di connessione

1. **Connect** crea o aggiorna il profilo FCC, registra l'entry `FCC`, seleziona il profilo
   e imposta `deploymentMode: "3p"`.
2. **Refresh**, eseguito all'avvio del server e su richiesta, aggiorna endpoint e credenziali
   solo se il profilo FCC è ancora attivo; non riattiva un profilo disconnesso.
3. **Disconnect** rimuove il profilo e l'entry FCC. Quando il profilo FCC era selezionato,
   seleziona un profilo Default vuoto e riporta `deploymentMode` a `"1p"`.

La selezione nativa già applicata dall'utente non viene sovrascritta. Tuttavia, il
comportamento corrente non ripristina il profilo nativo che era attivo prima di Connect:
questo richiede ancora il lifecycle reversibile descritto in
[`claude-desktop-gateway-login-analysis.md`](claude-desktop-gateway-login-analysis.md) e
[`claude-desktop-gateway-login-implementation-plan.md`](claude-desktop-gateway-login-implementation-plan.md).

## Limiti noti

- In modalità 3P il sign-in standard Claude.ai e il gateway FCC non governano la stessa
  sessione. Il Disconnect riporta al percorso di accesso standard quando il profilo FCC era
  selezionato, ma non ricostruisce il profilo nativo precedente.
- I connector ospitati da Anthropic e il contenuto sincronizzato dall'account Claude.ai
  restano disponibili soltanto nel Desktop standard. Le estensioni locali 3P possono essere
  installate dai marketplace configurati.
- La registrazione dei marketplace non installa plugin automaticamente e non garantisce la
  sincronizzazione continua dell'inventario Claude.ai.
- L'import Claude.ai supportato da Desktop è una copia one-shot e deve essere abilitato
  esplicitamente; non trasferisce plugin personali, connector o accessi OAuth.
- Il contesto da 1M dipende dai limiti reali del provider selezionato.
- FCC modifica soltanto installazioni Desktop non gestite. Le policy organizationali vengono
  rilevate e l'integrazione viene rifiutata.

## Verifica

Test mirati per profilo, credenziali, marketplace e discovery:

```powershell
uv run pytest -q tests/harnesses/test_claude_desktop_integration.py tests/api/test_claude_desktop_integration.py tests/api/test_model_listing.py
```

Controlli statici:

```powershell
uv run ruff format --check src/free_claude_code/harnesses/claude_desktop_integration.py src/free_claude_code/api/model_catalog.py tests/harnesses/test_claude_desktop_integration.py tests/api/test_model_listing.py
uv run ruff check src/free_claude_code/harnesses/claude_desktop_integration.py src/free_claude_code/api/model_catalog.py tests/harnesses/test_claude_desktop_integration.py tests/api/test_model_listing.py
uv run ty check src/free_claude_code/harnesses/claude_desktop_integration.py src/free_claude_code/api/model_catalog.py
```
