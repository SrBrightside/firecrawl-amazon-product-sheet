# Firecrawl Amazon search results

A small demo that turns a [Firecrawl](https://www.firecrawl.dev) Amazon **search results page** into a mobile SERP: a vertical list of product cards (image, title, rating, price, delivery, add-to-cart), not a single product detail page.

The hosted page is static. It ships a preloaded scrape of `https://www.amazon.com/s?k=Play+5`. You can open it with no API key. Phone layout first; on desktop it stays a list.

Live demo: https://srbrightside.github.io/firecrawl-amazon-product-sheet/

This is not an Amazon product, not Amazon Business, and not a production crawler.

## What you get

| File | Role |
| --- | --- |
| `index.html` | Mobile SERP UI. Reads embedded / `results.json`. |
| `results.json` | Array of organic hits plus one sponsored card, parsed from Firecrawl markdown. |
| `serve.py` | Optional local server. `POST /api/search` scrapes `amazon.com/s?k=…`. |

Each hit: `asin`, `title`, `url`, `image`, `rating`, `reviewCount`, `price` / `priceLabel` / `mapHidden`, `boughtPastMonth`, `delivery`, `extra` (ESRB), `brand`, `sponsored`, `badge`.

## View the demo

Open the Pages URL, or locally:

```bash
python3 serve.py
# http://127.0.0.1:8765
```

## Live search

The search box posts to `/api/search`. That route lives on a host with server-side functions (Vercel). It scrapes `amazon.com/s?k=…` with Firecrawl. The API key is a server env var, never in the HTML.

GitHub Pages can still show the preloaded Play 5 list, but it cannot search live.

Locally:

```bash
npx -y firecrawl-cli@latest login --browser
python3 serve.py
```

## Limits

- The Overall Pick often hides the buy-box price.
- Filter chips are static in the public page.
- Keyless Firecrawl 429s on shared IPs. Use a free login.

Scraping Amazon may conflict with Amazon’s conditions of use. This repo visualizes Firecrawl output under your own account.

## License

MIT. See `LICENSE`.
