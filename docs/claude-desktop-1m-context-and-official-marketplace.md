# Claude Desktop: contesto 1M e marketplace ufficiali

Status: ricerca e implementazione completate
Data: 2026-11-17
Ambito: profilo gateway FCC per Claude Desktop in modalità third-party (3P)

Panoramica del profilo FCC e delle altre migliorie implementate:
[`claude-desktop-fcc-profile.md`](claude-desktop-fcc-profile.md).

## Sintesi

Il profilo gateway FCC creato da Free Claude Code ora abilita:

- `modelPrefer1mContext: true`, così Claude Desktop preferisce la variante da un milione
  di token per i modelli che la supportano;
- `allowedPluginMarketplaces`, con i marketplace ufficiali Anthropic
  `anthropics/claude-plugins-official` e `anthropics/knowledge-work-plugins` registrati come
  disponibili.

La configurazione è scritta nel profilo FCC in
`src/free_claude_code/harnesses/claude_desktop_integration.py`. Il refresh del profilo
ripristina i due default FCC, ma conserva eventuali marketplace aggiuntivi configurati
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

Per rendere il segnale utile nel gateway FCC, la vista Desktop di `GET /v1/models` espone
ora `supports_1m: true` per i modelli il cui catalogo provider dichiara una finestra di
almeno 1.000.000 token. La vista CLI resta invariata e continua a esporre le sole
metadati documentati per la discovery Claude Code.

La preferenza non aumenta la capacità del provider. Il modello a valle deve accettare la
richiesta e il percorso di traduzione deve inoltrare l'header beta `context-1m-2025-08-07`
quando richiesto dal client. FCC conserva gli header `anthropic-beta` ricevuti nel percorso
Anthropic Messages, ma il provider finale deve supportare la beta e la sua finestra reale.

Il contesto 1M nel Claude Code CLI è un problema distinto: si seleziona un alias come
`sonnet[1m]` o `opus[1m]`, oppure si corregge la finestra di un ID custom con le impostazioni
previste dalla documentazione model-config. La modifica FCC riguarda il profilo Desktop 3P.

Fonti:

- <https://claude.com/docs/third-party/claude-desktop/configuration#modelprefer1mcontext>
- <https://claude.com/docs/third-party/claude-desktop/gateway#context-window-and-compaction>
- <https://claude.com/docs/third-party/claude-desktop/models>
- <https://code.claude.com/docs/en/model-config>
- <https://code.claude.com/docs/en/llm-gateway-protocol#feature-pass-through>

### Marketplace ufficiali di plugin e skill

FCC registra due marketplace ufficiali Anthropic:

| Repository | Nome manifest | Contenuto |
| --- | --- | --- |
| `anthropics/claude-plugins-official` | `claude-plugins-official` | marketplace generale di plugin e skill |
| `anthropics/knowledge-work-plugins` | `knowledge-work-plugins` | plugin per il lavoro in Cowork |

Entrambi i repository sono pubblici, usano `.claude-plugin/marketplace.json` e possono
essere consultati con accesso anonimo. Claude Code CLI registra automaticamente il primo
marketplace alla prima sessione terminale interattiva, salvo una policy managed. Claude
Desktop 3P usa invece la chiave di configurazione `allowedPluginMarketplaces`. FCC registra
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
separato, specializzato in esempi e skill; non viene registrato automaticamente da FCC. La
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

## Comportamento implementato

- Connect e Reconnect creano o aggiornano il profilo FCC con
  `modelPrefer1mContext: true`.
- Connect e Reconnect garantiscono la presenza dei marketplace
  `anthropics/claude-plugins-official` e `anthropics/knowledge-work-plugins`.
- Refresh ripristina `modelPrefer1mContext: true` se il profilo è stato modificato.
- Refresh conserva marketplace aggiuntivi e una configurazione personalizzata del marketplace
  ufficiale già presente.
- La discovery Desktop marca con `supports_1m: true` soltanto i modelli con una finestra
  provider nota e almeno 1.000.000 token.
- La discovery CLI non cambia.

## Verifica

Test mirati:

```powershell
uv run pytest -q tests/harnesses/test_claude_desktop_integration.py tests/api/test_model_listing.py
```

Controlli statici:

```powershell
uv run ruff format --check src/free_claude_code/harnesses/claude_desktop_integration.py src/free_claude_code/api/model_catalog.py tests/harnesses/test_claude_desktop_integration.py tests/api/test_model_listing.py
uv run ruff check src/free_claude_code/harnesses/claude_desktop_integration.py src/free_claude_code/api/model_catalog.py tests/harnesses/test_claude_desktop_integration.py tests/api/test_model_listing.py
uv run ty check src/free_claude_code/harnesses/claude_desktop_integration.py src/free_claude_code/api/model_catalog.py
```
