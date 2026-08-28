# Firecrawl Amazon search results

A small demo that turns a [Firecrawl](https://www.firecrawl.dev) Amazon **search results page** into a mobile SERP: search bar, chips, and a vertical list of product cards. Not a product detail page.

Live search: https://firecrawl-amazon-serp.vercel.app

Type in the box (try `kindle`). The page calls `GET /api/search?q=…`, which scrapes `amazon.com/s?k=…` with Firecrawl on the server. The API key is a Vercel env var. It never goes in the HTML, git, or the browser.

GitHub Pages still hosts a frozen Play 5 scrape if you only want the layout, no backend: https://srbrightside.github.io/firecrawl-amazon-product-sheet/

This is not an Amazon product, not Amazon Business, and not a production crawler.

## Layout

| File | Role |
| --- | --- |
| `index.html` | Mobile SERP UI. Preloads `results.json`, then hits `/api/search`. |
| `results.json` | Frozen Play 5 list (16 organic + 1 sponsored). |
| `api/search.py` | Vercel function: scrape + parse. Serves `/` and `/api/search`. |
| `scripts/serve.py` | Local server on port 8765. |

Each hit: `asin`, `title`, `url`, `image`, `rating`, `reviewCount`, `price` / `priceLabel` / `mapHidden`, `boughtPastMonth`, `delivery`, `extra`, `brand`, `sponsored`, `badge`.

## Run it locally

```bash
python3 scripts/serve.py
# http://127.0.0.1:8765
```

That shows the preloaded list. For live queries, log in to Firecrawl first:

```bash
npx -y firecrawl-cli@latest login --browser
python3 scripts/serve.py
```

Or set `FIRECRAWL_API_KEY` in the environment (never commit it). The `.env` in this repo is a stub.

## Limits

- The Overall Pick often hides the buy-box price.
- Filter chips are decorative.
- Keyless Firecrawl 429s on shared IPs. Use a free login or a host env var.
- Scraping Amazon may conflict with Amazon’s conditions of use. This repo visualizes Firecrawl output under your own account.

## License

MIT. See `LICENSE`.
