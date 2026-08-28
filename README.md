# Firecrawl Amazon Product Sheet

A small demo that turns a [Firecrawl](https://www.firecrawl.dev) Amazon **search results page** into a SERP: a list of product cards (image, title, price, rating), not a single product detail page.

The hosted page is static. It ships a preloaded scrape of `https://www.amazon.com/s?k=Play+5` (16 organic results). You can open the page with no API key. The layout is responsive (phone and desktop).

Live demo: https://srbrightside.github.io/firecrawl-amazon-product-sheet/

This is not an Amazon product, not Amazon Business, and not a production crawler.

## What you get

| File | Role |
| --- | --- |
| `index.html` | SERP UI. Reads `results.json` (or the JSON embedded in the page). |
| `results.json` | Array of organic search hits parsed from the Firecrawl markdown. |
| `serve.py` | Optional local server. `POST /api/search` scrapes `amazon.com/s?k=…` and returns the same JSON shape. |

Each hit: `asin`, `title`, `url`, `image`, `rating`, `reviewCount`, `price` / `priceLabel` / `mapHidden`, `boughtPastMonth`, `delivery`.

## View the demo

Open the Pages URL, or locally:

```bash
python3 serve.py
# http://127.0.0.1:8765
```

## Live search (clone)

Live search talks to Firecrawl from **your machine**. The key stays in the CLI store, never in the HTML.

```bash
npx -y firecrawl-cli@latest login --browser
python3 serve.py
```

Then submit a query in the page. The server scrapes `https://www.amazon.com/s?k={query}` and parses organic cards.

## Limits

- The first hit often hides the buy-box price (“Click to see price”).
- Sponsored/aax creatives are dropped; organic `sr_1_*` cards are kept.
- Keyless Firecrawl 429s on shared IPs. Use a free login.

Scraping Amazon may conflict with Amazon’s conditions of use. This repo visualizes Firecrawl output under your own account.

## License

MIT. See `LICENSE`.
