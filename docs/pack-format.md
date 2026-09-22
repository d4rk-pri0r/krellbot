# Pack format

A pack is a JSON file. One file, one pack. Put it in `~/.krellbot/packs/`.

The client reads the file. It does not execute code from it. A pack is not an order.

Required:

- `id` — short name, no spaces
- `public_label` — the name `krellbot list` prints

Optional:

- `rule` — one sentence, your words
- `timeframe` — such as `1h`
- `venue_of_history` — the venue the history came from
- `window_start` and `window_end` — required if you include `return_pct`
- `return_pct`, `max_drawdown_pct`, `trades`, `spark` — only if you have a real window

Do not invent a return. A number without dates is not a result.

```json
{
  "id": "mine",
  "public_label": "Mine",
  "rule": "Replace this sentence with your own rule.",
  "origin": "Written on this machine.",
  "timeframe": "1h"
}
```

Save that as `~/.krellbot/packs/mine.json`, then run `krellbot list`.

The packs we maintain are not in this repository.
