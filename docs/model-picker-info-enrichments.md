## Cosa ho scoperto

La base attuale è già corretta:

- Il titolo risolto con override curated → `models.dev` → euristica → reference grezza in `application/model_titles.py:52-67`.
- Il provider viene già mostrato nella `description` in `application/model_catalog.py:154-163`.
- Claude Code Terminal e Claude Desktop condividono la stessa proiezione in `api/model_catalog.py:172-204`.
- Il protocollo discovery, però, legge soltanto `id`, `display_name` e `description`; non esistono campi nativi per context window, prezzi, badge o grouping. Fonti: [Claude gateway discovery](https://code.claude.com/docs/en/llm-gateway-protocol#model-discovery) e [modelPicker](https://code.claude.com/docs/en/settings-reference#modelpicker).

Quindi le informazioni aggiuntive possono essere inserite principalmente nella `description`, ma il risultato deve essere una singola riga compatta.

## Informazioni consigliate

| Priorità | Informazione | Fonte | Valutazione |
|---|---|---|---|
| **P0** | Descrizione specifica del modello | `models.dev` | Già presente nella cache (`providers/model_catalog_source.py:125-155`), ma attualmente scartata: FCC mostra solo il nome del provider. È il migliorlioramento immediato. |
| **P0** | Context window | Provider listing / FCC | Già disponibile in `CatalogModel.context_window_tokens`; utile per distinguere modelli con 128K, 200K, 1M di contesto. |
| **P0** | Output massimo | Provider listing / FCC | Già disponibile in `CatalogModel.max_output_tokens`. |
| **P0** | Reasoning | Provider listing / `models.dev` | Già presente come `supports_reasoning`; utile per distinguere modelli reasoning-only e varianti “no thinking”. |
| **P0** | Modalità di input | Provider listing | `text`/`image` sono già supportati da FCC. Mostrare “vision” solo se il provider e il percorso di traduzione lo confermano. |
| **P1** | Tool calling / structured output | `models.dev`, con verifica provider | Molto utile per un ambiente di coding, ma non deve essere mostrato come `false` quando il dato è semplicemente assente. |
| **P1** | Stato del modello | `models.dev.status` | `alpha`, `beta`, `deprecated`. I modelli deprecati dovrebbero essere segnalati, non necessariamente rimossi. |
| **P1** | Costo indicativo | `models.dev.cost` | Input/output/reasoning/cache per milione di token. È provider-specific e può diventare obsoleto: mostrarlo solo come “list price”. |
| **P1** | Data di rilascio / ultimo aggiornamento | `models.dev` | Aiuta a distinguere versioni e alias; meno utile rispetto a context e output. |
| **P2** | Canonical model identity | `models.dev.canonical_model_id` | Utile per distinguere alias hosted dallo stesso modello, ma il valore è tecnico e lungo. |
| **P2** | Open weights / licenza | `models.dev` | Interessante per modelli open-weight; la licenza è troppo verbosa per il picker. |
| **P2** | Benchmark | `models.dev.benchmarks` | Non consigliato nel picker: punteggi non sempre confrontabili e richiedono harness, dataset e fonte. |
| **P2** | Link a model card, paper o weights | `models.dev.links` / `weights` | Non renderizzabili come link nel protocollo attuale; meglio in una pagina di dettaglio o nell’Admin UI. |
| **P2** | Logo provider/lab | `models.dev` | models.dev espone gli SVG, ma il picker discovery non ha un campo logo. |

## Un esempio realistico

Attualmente la riga è essenzialmente:

```text
MiniMax-M3.1-Flash
NVIDIA NIM
```

Una versione più informativa potrebbe essere:

```text
MiniMax-M3.1-Flash
MiniMax · NVIDIA NIM · 1M context · 512K output · reasoning · vision · tools
```

Oppure, se si preferisce mostrare la descrizione del modello:

```text
MiniMax-M3.1-Flash
Frontier multimodal coding model · NVIDIA NIM · 1M context · reasoning
```

La seconda forma è probabilmente la più leggibile. La `description` dovrebbe rimanere breve, circa 120–180 caratteri, perché Claude Code la mostra come testo secondario e il Desktop potrebbe applicare un’ulteriore compressione.

## Dati già disponibili internamente ma non mostrati

Il caso più interessante è che FCC già conosce:

- reasoning;
- input modalities;
- context window;
- max output tokens;

in `application/model_catalog.py:31-43` e `application/model_metadata.py:9-20`.

La vista `messages`/`responses` li serializza già in `api/model_catalog.py:233-259`, mentre la vista Claude/Desktop no. Non è quindi necessario inventare una nuova pipeline: basta arricchire la `description` della proiezione Claude, mantenendo invariati gli ID e il routing.

## Cosa eviterei

- **Logo/badge grafici:** non esistono nel protocollo discovery.
- **Benchmark completi:** troppo rumorosi e potenzialmente non comparabili.
- **Prezzi come dato definitivo:** il prezzo reale può cambiare per provider, piano o contratto.
- **Audio/video/PDF:** FCC espone attualmente solo `text` e `image`; non bisogna promettere capacità non preservate dal percorso di traduzione.
- **Sostituire gli ID con ID canonici:** `canonical_model_id` serve solo come metadato; gli ID pubblicati devono restare quelli usati dal routing.
- **Riscrivere `inferenceModels` o `labelOverride`:** sono owned dall’utente e il Desktop deve preservarli invariati.

## Ordine di implementazione consigliato

1. Estendere la cache models.dev per mantenere descrizione, limiti, reasoning, modalities, status e cost.
2. Aggiungere un formatter compatto della `description` per Claude/Desktop.
3. Usare sempre i limiti e le capability del provider FCC; usare models.dev per arricchire i dati mancanti.
4. Aggiungere un test che garantisca che la descrizione cambi ma ID, routing e fallback restino identici.
5. Verificare la resa reale nel picker Desktop, perché il protocollo garantisce il campo ma non il layout grafico.

Fonti principali: [models.dev README/schema](https://github.com/anomalyco/models.dev/blob/dev/README.md), [API models.dev](https://models.dev/api.json), [catalogo canonico](https://models.dev/models.json), [gateway discovery Claude](https://code.claude.com/docs/en/llm-gateway-protocol#model-discovery).