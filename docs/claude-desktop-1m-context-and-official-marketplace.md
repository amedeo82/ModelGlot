# Claude Desktop: contesto 1M e marketplace ufficiali

Status: ricerca e implementazione completate
Data: 2026-11-27
Ambito: profilo gateway ModelGlot per Claude Desktop in modalità third-party (3P)

Panoramica del profilo ModelGlot e delle altre migliorie implementate:
[`claude-desktop-modelglot-profile.md`](claude-desktop-modelglot-profile.md).

## Sintesi

Il profilo gateway ModelGlot creato da ModelGlot ora abilita:

- `modelPrefer1mContext: true`, così Claude Desktop preferisce la variante da un milione
  di token per i modelli che la supportano;
- `allowedPluginMarketplaces`, con tutti i cinque marketplace mostrati da **Curated by
  Anthropic** il 2026-11-27 registrati come disponibili: Claude Code, Cowork, Financial
  Services, Legal e Life Sciences.

La configurazione è scritta nel profilo ModelGlot in
`src/modelglot/harnesses/claude_desktop_integration.py`. Il refresh del profilo
ripristina i cinque default ModelGlot, ma conserva eventuali marketplace aggiuntivi configurati
dall'utente e le personalizzazioni dei marketplace ufficiali già presenti.

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

ModelGlot registra tutti i marketplace raggruppati da Claude Desktop sotto **Curated by
Anthropic** nella schermata verificata il 2026-11-27:

| Voce Desktop | Repository | Nome `marketplace.json` |
| --- | --- | --- |
| Claude Code plugins | `anthropics/claude-plugins-official` | `claude-plugins-official` |
| Cowork plugins | `anthropics/knowledge-work-plugins` | `knowledge-work-plugins` |
| Claude for Financial Services | `anthropics/financial-services` | `claude-for-financial-services` |
| Claude for Legal | `anthropics/claude-for-legal` | `claude-for-legal` |
| Claude for Life Sciences | `anthropics/life-sciences` | `life-sciences` |

I repository sono pubblici, usano `.claude-plugin/marketplace.json` e sono stati verificati
con accesso anonimo sul branch `main`. In particolare, il nome del marketplace Financial
Services non coincide con il nome del repository: `expectedName` deve essere
`claude-for-financial-services`. I marketplace **From partners**, il marketplace separato
`anthropics/skills` e la directory Claude Marketplace su `claude.ai` non fanno parte di
questo default.

Claude Code CLI registra automaticamente `claude-plugins-official` alla prima sessione
terminale interattiva, salvo una policy managed. Claude Desktop 3P non aggiunge invece da solo
i marketplace Curated by Anthropic: usa la chiave `allowedPluginMarketplaces`. ModelGlot
registra quindi:

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
    },
    {
      "source": "github",
      "repo": "anthropics/financial-services",
      "ref": "main",
      "expectedName": "claude-for-financial-services",
      "installationPreference": "available",
      "credentialKind": "anonymous"
    },
    {
      "source": "github",
      "repo": "anthropics/claude-for-legal",
      "ref": "main",
      "expectedName": "claude-for-legal",
      "installationPreference": "available",
      "credentialKind": "anonymous"
    },
    {
      "source": "github",
      "repo": "anthropics/life-sciences",
      "ref": "main",
      "expectedName": "life-sciences",
      "installationPreference": "available",
      "credentialKind": "anonymous"
    }
  ]
}
```

`installationPreference: "available"` registra i cataloghi senza installare
automaticamente tutti i plugin. L'utente può scegliere i plugin da **Customize → Plugins →
Discover → Organization**, sia in Cowork sia in Code. `available` consente di seguire il branch
`main`; le preferenze `auto_install` e `required` richiedono invece un commit SHA completo di
40 caratteri e una distribuzione governata con pin di revisione. Per questo il default
ModelGlot non installa automaticamente codice eseguibile e non blocca gli aggiornamenti su un
commit che richiederebbe manutenzione manuale.

Desktop 3P sincronizza i plugin il cui contenuto è relativo al repository del marketplace.
Le voci dei manifest ufficiali che puntano a un altro repository non vengono scaricate da
questa configurazione e quindi non compaiono nella scheda Organization. Al 2026-11-27 le voci
dei tre nuovi manifest usano sorgenti relative al rispettivo repository. La registrazione
abilita i marketplace ufficiali senza promettere la sincronizzazione di voci esterne presenti
in altri cataloghi o introdotte successivamente.

I plugin possono eseguire hook, script, monitor e server MCP con i permessi dell'utente.
Anche un marketplace ufficiale richiede quindi che l'utente valuti il plugin prima di
installarlo. Per i marketplace Git il dispositivo deve avere Git installato e accesso di rete a
GitHub; il download del marketplace avviene sull'host e non dipende da
`coworkEgressAllowedHosts`.

### MCP e connettori nei profili gateway 3P

La scheda **Code** di Claude Desktop incorpora Claude Code e traduce automaticamente la
configurazione 3P del profilo per il motore Claude Code. Non bisogna copiare questi valori in
`~/.claude/settings.json` o in `~/.claude.json`: quelle configurazioni appartengono al Claude
Code standalone o alle impostazioni utente e non sono il meccanismo con cui ModelGlot popola il
profilo Desktop.

La documentazione ufficiale distingue tre casi:

1. **Server MCP dichiarati da un plugin.** Dopo l'installazione del plugin, i server remoti del
   suo `.mcp.json` possono essere usati nelle sessioni Cowork, Chat e Code che caricano quel
   plugin. Non serve duplicarli in `managedMcpServers`. L'eventuale accesso OAuth resta
   separato tra Code e il resto di Desktop.
2. **Connettori gestiti autonomi.** Un server remoto HTTP/SSE o locale stdio che non appartiene
   a un plugin si distribuisce con `managedMcpServers`. Le voci esterne richiedono `name` e
   `transport`, oltre a `url` o `command`; il campo `type` usato dal `.mcp.json` di un plugin
   non sostituisce `transport`. ModelGlot non inventa endpoint, credenziali o connettori e
   lascia invariate eventuali voci già configurate dall'utente.
3. **Sostituzione o autenticazione di un server del plugin.** Una voce `managedMcpServers` con
   lo stesso nome può sostituire il server del plugin quando servono, per esempio, un headers
   helper o una configurazione OAuth gestita. Non è un requisito generale per rendere
   disponibili gli MCP dei marketplace.

Il profilo ModelGlot non imposta `allowedPluginMcpServers` o `deniedPluginMcpServers`: una
lista allowed vuota bloccherebbe tutti i server remoti dei plugin e, una volta impostata,
escluderebbe anche i server locali stdio dei plugin. Non imposta nemmeno
`isLocalDevMcpEnabled: false`, perché disabiliterebbe gli MCP locali dei plugin. I valori di
default documentati (`allowedPluginMcpServers` assente = nessun limite,
`isLocalDevMcpEnabled` assente = `true`) mantengono quindi utilizzabili gli MCP dei plugin
installati senza introdurre una allowlist di rete globale. Eventuali policy già presenti nel
profilo vengono conservate.

Analogamente ModelGlot non imposta `userPluginMarketplacesEnabled: false`: quel valore
nasconderebbe i marketplace aggiunti dall'utente, in conflitto con il contratto di
conservazione del profilo. I cinque marketplace gestiti sono quindi garantiti, senza trasformare
questa modifica in una restrizione delle personalizzazioni esistenti. Le policy Claude Code
managed esterne possono avere precedenza; per combinarle con quelle generate da Desktop la
documentazione richiede `parentSettingsBehavior: "merge"` nella policy Claude Code, non nel
profilo ModelGlot.

### Piano di implementazione aggiornato

1. Estendere `_OFFICIAL_MARKETPLACES` con i tre repository e i nomi manifest verificati,
   mantenendo l'ordine mostrato da Desktop.
2. Continuare a generare ogni voce con `source: "github"`, `ref: "main"`,
   `installationPreference: "available"` e `credentialKind: "anonymous"`.
3. Riutilizzare il merge esistente: Connect/Reconnect/Refresh aggiungono solo le voci mancanti,
   senza sovrascrivere una configurazione ufficiale personalizzata né rimuovere marketplace
   aggiuntivi.
4. Non aggiungere o modificare `managedMcpServers`, le allow/deny list MCP o le capability
   degli MCP locali; preservare i valori utente già presenti.
5. Estendere i test del profilo fresco e del refresh a tutti i cinque marketplace e aggiungere
   un regression test per la conservazione delle configurazioni MCP.
6. Aggiornare questo piano, la guida del profilo e il README nello stesso cambiamento.

Criteri di accettazione: il JSON del profilo contiene esattamente i cinque default nell'ordine
previsto, un secondo refresh è idempotente, un profilo esistente riceve soltanto i default
mancanti e nessun connettore o policy MCP viene creato o cancellato. La verifica manuale
successiva consiste nel riavviare Desktop, attendere la sincronizzazione e controllare le cinque
sotto-schede Organization; l'installazione dei singoli plugin resta una scelta esplicita.

Fonti:

- <https://code.claude.com/docs/en/plugins/anthropic-marketplaces>
- <https://code.claude.com/docs/en/plugins/overview>
- <https://github.com/anthropics/claude-plugins-official>
- <https://github.com/anthropics/knowledge-work-plugins>
- <https://github.com/anthropics/financial-services>
- <https://github.com/anthropics/claude-for-legal>
- <https://github.com/anthropics/life-sciences>
- <https://claude.com/docs/third-party/claude-desktop/admin-console#plugin-marketplaces>
- <https://claude.com/docs/third-party/claude-desktop/extensions#plugin-marketplaces-admin>
- <https://claude.com/docs/third-party/claude-desktop/extensions#remote-mcp-servers-in-plugins>
- <https://claude.com/docs/third-party/claude-desktop/code>
- <https://claude.com/docs/third-party/claude-desktop/configuration#allowedpluginmarketplaces>
- <https://claude.com/docs/third-party/claude-desktop/configuration#managedmcpservers>
- <https://claude.com/docs/third-party/claude-desktop/configuration#allowedpluginmcpservers>
- <https://claude.com/docs/third-party/claude-desktop/configuration#islocaldevmcpenabled>
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
- Connect e Reconnect garantiscono la presenza dei cinque marketplace Curated by Anthropic
  elencati sopra.
- Refresh ripristina `modelPrefer1mContext: true` se il profilo è stato modificato.
- Refresh conserva marketplace aggiuntivi, le configurazioni personalizzate dei marketplace
  ufficiali già presenti e tutte le configurazioni MCP esistenti.
- Il profilo non aggiunge connettori gestiti e non limita gli MCP remoti o locali dei plugin.
- La discovery Desktop marca con `supports_1m: true` soltanto i modelli con una finestra
  provider nota e almeno 1.000.000 token.
- La discovery CLI non cambia.
- L'import Claude.ai e `automatic3pImport` non sono ancora configurati dal profilo ModelGlot.
  Il piano per un'attivazione esplicita e one-shot è documentato sopra; non esiste una
  sincronizzazione continua dell'account.

## Verifica

Test mirati:

```powershell
uv run --locked pytest -q tests/harnesses/test_claude_desktop_integration.py tests/api/test_model_listing.py
```

Controlli statici:

```powershell
uv run --locked ruff format --check src/modelglot/harnesses/claude_desktop_integration.py src/modelglot/api/model_catalog.py tests/harnesses/test_claude_desktop_integration.py tests/api/test_model_listing.py
uv run --locked ruff check src/modelglot/harnesses/claude_desktop_integration.py src/modelglot/api/model_catalog.py tests/harnesses/test_claude_desktop_integration.py tests/api/test_model_listing.py
uv run --locked pyrefly check src/modelglot/harnesses/claude_desktop_integration.py src/modelglot/api/model_catalog.py
```
