# Claude Desktop: contesto 1M e marketplace ufficiali

Status: ricerca e implementazione completate
Data: 2026-11-17
Ambito: profilo gateway ModelGlot per Claude Desktop in modalità third-party (3P)

Panoramica del profilo ModelGlot e delle altre migliorie implementate:
[`claude-desktop-modelglot-profile.md`](claude-desktop-modelglot-profile.md).

## Sintesi

Il profilo gateway ModelGlot creato da ModelGlot ora abilita:

- `modelPrefer1mContext: true`, così Claude Desktop preferisce la variante da un milione
  di token per i modelli che la supportano;
- `allowedPluginMarketplaces`, con i marketplace ufficiali Anthropic
  `anthropics/claude-plugins-official` e `anthropics/knowledge-work-plugins` registrati come
  disponibili.

La configurazione è scritta nel profilo ModelGlot in
`src/modelglot/harnesses/claude_desktop_integration.py`. Il refresh del profilo
ripristina i due default ModelGlot, ma conserva eventuali marketplace aggiuntivi configurati
dall'utente.

## Ricerca

### Contesto da 1M token

Claude Desktop in modalità 3P non legge il routing del gateway da `ANTHROPIC_BASE_URL` o da
`~/.claude/settings.json`: usa il profilo di inferenza third-party. La chiave ufficiale per
la preferenza da 1M è:

```json
{
  "modelPrefer1mContext": true
}
```

La chiave è disponibile da Claude Desktop 1.28929.0. Ha effetto sui modelli che il client
riconosce come dotati di una finestra da 1M. Nella configurazione esplicita
`inferenceModels`, il modello deve avere `supports1m: true`; con il model discovery del
gateway, il client accetta anche `supports_1m: true` oppure `max_input_tokens` almeno
1.000.000.

Per rendere il segnale utile nel gateway ModelGlot, la vista Desktop di `GET /v1/models` espone
ora `supports_1m: true` per i modelli il cui catalogo provider dichiara una finestra di
almeno 1.000.000 token. La vista CLI resta invariata e continua a esporre le sole
metadati documentati per la discovery Claude Code.

La preferenza non aumenta la capacità del provider. Il modello a valle deve accettare la
richiesta e il percorso di traduzione deve inoltrare l'header beta `context-1m-2025-08-07`
quando richiesto dal client. ModelGlot conserva gli header `anthropic-beta` ricevuti nel percorso
Anthropic Messages, ma il provider finale deve supportare la beta e la sua finestra reale.

Il contesto 1M nel Claude Code CLI è un problema distinto: si seleziona un alias come
`sonnet[1m]` o `opus[1m]`, oppure si corregge la finestra di un ID custom con le impostazioni
previste dalla documentazione model-config. La modifica ModelGlot riguarda il profilo Desktop 3P.

Fonti:

- <https://claude.com/docs/third-party/claude-desktop/configuration#modelprefer1mcontext>
- <https://claude.com/docs/third-party/claude-desktop/gateway#context-window-and-compaction>
- <https://claude.com/docs/third-party/claude-desktop/models>
- <https://code.claude.com/docs/en/model-config>
- <https://code.claude.com/docs/en/llm-gateway-protocol#feature-pass-through>

### Marketplace ufficiali di plugin e skill

ModelGlot registra due marketplace ufficiali Anthropic:

| Repository | Nome manifest | Contenuto |
| --- | --- | --- |
| `anthropics/claude-plugins-official` | `claude-plugins-official` | marketplace generale di plugin e skill |
| `anthropics/knowledge-work-plugins` | `knowledge-work-plugins` | plugin per il lavoro in Cowork |

Entrambi i repository sono pubblici, usano `.claude-plugin/marketplace.json` e possono
essere consultati con accesso anonimo. Claude Code CLI registra automaticamente il primo
marketplace alla prima sessione terminale interattiva, salvo una policy managed. Claude
Desktop 3P usa invece la chiave di configurazione `allowedPluginMarketplaces`. ModelGlot registra
quindi:

```json
{
  "allowedPluginMarketplaces": [
    {
      "source": "github",
      "repo": "anthropics/claude-plugins-official",
      "ref": "main",
      "expectedName": "claude-plugins-official",
      "installationPreference": "available",
      "credentialKind": "anonymous"
    },
    {
      "source": "github",
      "repo": "anthropics/knowledge-work-plugins",
      "ref": "main",
      "expectedName": "knowledge-work-plugins",
      "installationPreference": "available",
      "credentialKind": "anonymous"
    }
  ]
}
```

`installationPreference: "available"` registra i cataloghi senza installare
automaticamente tutti i plugin. L'utente può scegliere i plugin da **Customize → Plugins →
Discover → Organization**. `available` consente di usare il branch `main`; le preferenze
`auto_install` e `required` richiedono invece un commit SHA completo e una distribuzione
governata con pin di revisione.

Il marketplace generale contiene plugin Anthropic che possono includere skill, ad esempio
`skill-creator`. Il marketplace `knowledge-work-plugins` raccoglie plugin dedicati ai
flussi di lavoro di Cowork come Productività, Vendite, Finanza, Dati, Marketing, Supporto
clienti e Gestione prodotto. Il repository `anthropics/skills` è un marketplace Anthropic
separato, specializzato in esempi e skill; non viene registrato automaticamente da ModelGlot. La
directory Claude Marketplace su `claude.ai` è a sua volta diversa dai marketplace Git di
Claude Code e non viene sincronizzata continuamente nell'identità 3P.

Desktop 3P sincronizza i plugin il cui contenuto è relativo al repository del marketplace.
Le voci dei manifest ufficiali che puntano a un altro repository non vengono scaricate da
questa configurazione e quindi non compaiono nella scheda Organization. La registrazione
abilita i marketplace ufficiali senza promettere la sincronizzazione dell'intero catalogo
di terze parti.

I plugin possono eseguire hook, script, monitor e server MCP con i permessi dell'utente.
Anche un marketplace ufficiale richiede quindi che l'utente valuti il plugin prima di
installarlo.

Fonti:

- <https://code.claude.com/docs/en/plugins/anthropic-marketplaces>
- <https://code.claude.com/docs/en/plugins/overview>
- <https://github.com/anthropics/knowledge-work-plugins>
- <https://claude.com/docs/third-party/claude-desktop/extensions#plugin-marketplaces-admin>
- <https://claude.com/docs/third-party/claude-desktop/configuration#allowedpluginmarketplaces>
- <https://code.claude.com/docs/en/plugins/security>

## Sincronizzazione con l'account Claude.ai

### Risultato della verifica

Claude Desktop in modalità 3P non offre una sincronizzazione continua dell'inventario
personale Claude.ai. Il marketplace `allowedPluginMarketplaces` sincronizza il contenuto
del repository che l'amministratore ha configurato, non i plugin installati, le skill
salvate, i connector o i relativi accessi OAuth dell'utente.

Anthropic distingue tre meccanismi:

| Meccanismo | Contenuto | Frequenza | Account Claude.ai |
| --- | --- | --- | --- |
| Marketplace gestito | Plugin e skill del repository configurato | Ricalcolo periodico, in genere circa ogni 10 minuti | No, salvo credenziali del marketplace |
| Import Claude.ai | Chat, progetti e artefatti dell'utente | Copia one-shot | Sì, con autorizzazione nel wizard |
| Import da un altro Desktop | Sessioni e dati locali selezionati, inclusi plugin caricati e skill salvate | Copia one-shot | Indiretta, tramite export del dispositivo |

L'import diretto dall'account Claude.ai non trasferisce l'inventario dei plugin, dei
connector, delle estensioni desktop o dei token OAuth. Un export creato da un altro
Claude Desktop può contenere plugin caricati e skill salvate, ma questi arrivano
disattivati e non include accessi ai connector, estensioni desktop, marketplace o
impostazioni dei plugin.

La documentazione ufficiale afferma esplicitamente che ogni import da Claude.ai è una
copia one-shot: l'attività successiva nel account non compare in Desktop finché l'utente
non esegue un nuovo import. Non esiste inoltre un'API pubblica documentata che enumeri i
plugin personali o i connector dell'account e li installi in un profilo 3P.

### Import Claude.ai supportato da Desktop

Claude Desktop espone la chiave `claudeAiImport`, disponibile dalla versione
`1.10628.0`. La forma minima per abilitare il wizard **Settings → Import & export** è:

```json
{
  "claudeAiImport": {
    "enabled": true,
    "bannerBehavior": "detect"
  }
}
```

I campi disponibili hanno semantica distinta:

| Campo | Semantica |
| --- | --- |
| `enabled` | Abilita il wizard; il valore predefinito è `false`. |
| `allowedOrganizationUuids` | Consente il sign-in solo per gli UUID Claude.ai indicati. Una lista vuota non consente alcuna importazione; un account personale viene rifiutato quando la lista è presente. |
| `automatic3pImport` | Copia una volta dati 3P precedenti presenti sul computer. Non importa l'account Claude.ai e non è controllato da `enabled`. |
| `exportEnabled` | Consente di esportare i dati locali per un altro dispositivo; richiede anche `enabled`. |
| `bannerBehavior` | Controlla il prompt `off`, `detect` o `show`. |

L'import con sign-in concede a Claude Desktop il permesso di richiedere una copia one-shot
dei dati dell'utente. ModelGlot non deve ricevere, copiare o memorizzare il token OAuth
Claude.ai: autenticazione, download dell'export e import devono restare nel processo
Desktop. Un export scaricato può contenere dati sensibili e non è cifrato.

Per le organizzazioni Team ed Enterprise, il workspace owner deve abilitare
**Allow members to export their own data**. Il flag non può essere attivato in
organizzazioni HIPAA-ready. `allowedOrganizationUuids` consente di limitare il wizard a
organizzazioni approvate, ma ModelGlot non deve indovinare o deduplicare tale UUID.

### Piano di implementazione ModelGlot raccomandato

L'attivazione dovrebbe essere un'azione esplicita e reversibile, non una conseguenza
silenziosa di Connect:

1. Aggiungere a
   `src/modelglot/harnesses/claude_desktop_integration.py` un'opzione separata
   per l'import Claude.ai. Non accorpare l'opzione a `modelPrefer1mContext` o ai
   marketplace, perché attiva un flusso OAuth e trasferisce dati dell'utente.
2. Quando l'opzione è attiva, scrivere soltanto
   `claudeAiImport.enabled: true` nel profilo ModelGlot e preservare gli altri campi
   `claudeAiImport` scelti dall'utente. Il refresh non deve riattivare un import
   disabilitato manualmente, a meno che ModelGlot non mantenga esplicitamente la policy.
3. Esporre lo stato nell'Admin API e nella card **Integrations**, indicando che
   l'import è one-shot e non una sincronizzazione continua.
4. Accettare `allowedOrganizationUuids` solo come allowlist esplicita fornita
   dall'amministratore. Non usare una lista vuota, perché disabiliterebbe l'import.
5. Non attivare `automatic3pImport` per impostazione predefinita: copia in background
   memoria, istruzioni, cartelle, task e plugin eseguibili senza una revisione
   granulare del contenuto importato.
6. Non attivare `exportEnabled` salvo richiesta esplicita, poiché produce un archivio ZIP
   non cifrato che può contenere password o chiavi API presenti nei plugin.
7. Per importare plugin caricati e skill salvate da un export di un altro Desktop,
   richiedere all'utente di abilitare anche `userPluginUploadsEnabled`,
   `skillCreationEnabled`, `scheduledTasksEnabled` e, per i server MCP locali,
   `isLocalDevMcpEnabled`. I plugin e le skill importate devono comunque essere
   riattivati manualmente.
8. Aggiungere test unitari per idempotenza, conservazione della allowlist, disattivazione
   tramite refresh, assenza di token nell'API e rollback; aggiungere un test manuale con
   una release Desktop supportata che verifichi il pulsante **Import…** e la copia
   one-shot senza scrivere sull'account remoto.

### Alternative per plugin e connector

Per avere plugin sempre aggiornati in 3P, la soluzione supportata è un marketplace
controllato dall'amministratore, erogato tramite `allowedPluginMarketplaces` con una
revisione Git o HTTPS pinnata. Il contenuto viene ricalcolato periodicamente dal
repository, ma questo non crea un ponte con l'inventario personale Claude.ai.

Per i connector, la soluzione supportata è `managedMcpServers`, con OAuth configurato per
il server remoto. I connector etichettati **Made by Anthropic** sono ospitati
sull'infrastruttura Anthropic e restano disponibili soltanto nel Desktop standard. Le
estensioni desktop locali sono caricate in 3P quando
`isDesktopExtensionEnabled` è attivo, ma la documentazione non offre una sincronizzazione
dell'inventario installato sull'account.

La Plugins API beta per organizzazioni Enterprise può essere valutata come pipeline di
inventario e ripubblicazione controllata: elencare plugin organizzativi, revisionarli e
pubblicarli in un marketplace governato. Non è un'API di sincronizzazione del profilo
Desktop 3P, non è disponibile per organizzazioni HIPAA-ready e non risolve il caso dei
plugin installati su un account personale.

Fonti:

- <https://claude.com/docs/third-party/claude-desktop/import>
- <https://claude.com/docs/third-party/claude-desktop/configuration#claudeaiimport>
- <https://claude.com/docs/third-party/claude-desktop/data-storage>
- <https://claude.com/docs/third-party/claude-desktop/extensions>
- <https://claude.com/docs/third-party/claude-desktop/overview>
- <https://platform.claude.com/docs/en/manage-claude/plugins-api>

## Comportamento implementato

- Connect e Reconnect creano o aggiornano il profilo ModelGlot con
  `modelPrefer1mContext: true`.
- Connect e Reconnect garantiscono la presenza dei marketplace
  `anthropics/claude-plugins-official` e `anthropics/knowledge-work-plugins`.
- Refresh ripristina `modelPrefer1mContext: true` se il profilo è stato modificato.
- Refresh conserva marketplace aggiuntivi e una configurazione personalizzata del marketplace
  ufficiale già presente.
- La discovery Desktop marca con `supports_1m: true` soltanto i modelli con una finestra
  provider nota e almeno 1.000.000 token.
- La discovery CLI non cambia.
- L'import Claude.ai e `automatic3pImport` non sono ancora configurati dal profilo ModelGlot.
  Il piano per un'attivazione esplicita e one-shot è documentato sopra; non esiste una
  sincronizzazione continua dell'account.

## Verifica

Test mirati:

```powershell
uv run pytest -q tests/harnesses/test_claude_desktop_integration.py tests/api/test_model_listing.py
```

Controlli statici:

```powershell
uv run ruff format --check src/modelglot/harnesses/claude_desktop_integration.py src/modelglot/api/model_catalog.py tests/harnesses/test_claude_desktop_integration.py tests/api/test_model_listing.py
uv run ruff check src/modelglot/harnesses/claude_desktop_integration.py src/modelglot/api/model_catalog.py tests/harnesses/test_claude_desktop_integration.py tests/api/test_model_listing.py
uv run ty check src/modelglot/harnesses/claude_desktop_integration.py src/modelglot/api/model_catalog.py
```
