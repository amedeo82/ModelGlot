# Claude Desktop: contesto 1M e marketplace ufficiale

Status: ricerca e implementazione completate
Data: 2026-11-16
Ambito: profilo gateway FCC per Claude Desktop in modalità third-party (3P)

## Sintesi

Il profilo gateway FCC creato da Free Claude Code ora abilita:

- `modelPrefer1mContext: true`, così Claude Desktop preferisce la variante da un milione
  di token per i modelli che la supportano;
- `allowedPluginMarketplaces`, con il marketplace ufficiale Anthropic
  `anthropics/claude-plugins-official` registrato come disponibile.

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

### Marketplace ufficiale di plugin e skill

Il marketplace ufficiale generale di Claude Code è:

| Campo | Valore |
| --- | --- |
| Repository | `anthropics/claude-plugins-official` |
| Nome | `claude-plugins-official` |
| Manifest | `.claude-plugin/marketplace.json` |
| Accesso | pubblico e anonimo |

Claude Code CLI registra automaticamente questo marketplace alla prima sessione terminale
interattiva, salvo una policy managed. Claude Desktop 3P usa invece la chiave di
configurazione `allowedPluginMarketplaces`. FCC registra quindi:

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
    }
  ]
}
```

`installationPreference: "available"` registra il catalogo senza installare automaticamente
tutti i plugin. L'utente può scegliere i plugin da **Customize → Plugins → Discover →
Organization**. `available` consente di usare il branch `main`; le preferenze
`auto_install` e `required` richiedono invece un commit SHA completo e una distribuzione
governata con pin di revisione.

Il marketplace contiene plugin Anthropic che possono includere skill, ad esempio
`skill-creator`. Il repository `anthropics/skills` è un marketplace Anthropic separato,
specializzato in esempi e skill; non viene registrato automaticamente da FCC. La directory
Claude Marketplace su `claude.ai` è a sua volta diversa dai marketplace Git di Claude Code e
non viene sincronizzata continuamente nell'identità 3P.

Desktop 3P sincronizza i plugin il cui contenuto è relativo al repository del marketplace.
Le voci del manifest ufficiale che puntano a un altro repository non vengono scaricate da
questa configurazione e quindi non compaiono nella scheda Organization. La registrazione
abilita il marketplace ufficiale senza promettere la sincronizzazione dell'intero catalogo
di terze parti.

I plugin possono eseguire hook, script, monitor e server MCP con i permessi dell'utente.
Anche un marketplace ufficiale richiede quindi che l'utente valuti il plugin prima di
installarlo.

Fonti:

- <https://code.claude.com/docs/en/plugins/anthropic-marketplaces>
- <https://code.claude.com/docs/en/plugins/overview>
- <https://claude.com/docs/third-party/claude-desktop/extensions#plugin-marketplaces-admin>
- <https://claude.com/docs/third-party/claude-desktop/configuration#allowedpluginmarketplaces>
- <https://code.claude.com/docs/en/plugins/security>

## Comportamento implementato

- Connect e Reconnect creano o aggiornano il profilo FCC con
  `modelPrefer1mContext: true`.
- Connect e Reconnect garantiscono la presenza del marketplace
  `anthropics/claude-plugins-official`.
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
