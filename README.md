# Firecrawl Amazon Product Sheet

A small demo that turns a [Firecrawl](https://www.firecrawl.dev) Amazon scrape into a product card.

Firecrawl returns messy markdown (nav, warranties, “also viewed”, MAP price copy). This project parses that markdown into JSON and paints a sheet: title, ASIN, rating, listed vs hidden price, bullets, images, and a coverage panel of what made it out versus what did not.

Live demo: https://srbrightside.github.io/firecrawl-amazon-product-sheet/

The hosted page is static. It ships a preloaded scrape of the Amazon query **Play 5** (it resolved to a PlayStation 5 console, ASIN `B0FRGTYSL5`). You can open the page with no API key.

This is not an Amazon product, not Amazon Business, and not a production crawler. Use it to see what Firecrawl actually returns.

## What you get

| File | Role |
| --- | --- |
| `index.html` | Single-file UI (HTML, CSS, JS). Reads `product.json`, or the JSON embedded in the page. |
| `product.json` | Structured record parsed from the Play 5 scrape. |
| `serve.py` | Optional local server. Serves the UI and `POST /api/search` for a live Firecrawl search + scrape. |

The JSON shape is the domain model: `title`, `asin`, `price.mapHidden` / `price.newCondition`, `rating`, `images`, `bullets`, `alsoViewed`, `searchHits`, `coverage.extracted`, `coverage.lost`.

## View the demo

Open `index.html` on GitHub Pages (or any static host) or locally:

```bash
python3 serve.py
# then http://127.0.0.1:8765
```

The Play 5 card loads from `product.json`. No Firecrawl key is in the HTML.

## Live search (clone this repo)

Live “search another product” talks to Firecrawl from **your machine**, never from the public page. The Firecrawl key stays in the CLI credential store.

1. Install Node 20+ (the CLI wants 22 if you can; 20 still runs).
2. Log in with a free Firecrawl account. Do not use the keyless tier from a shared IP; it 429s.

```bash
npx -y firecrawl-cli@latest login --browser
npx -y firecrawl-cli@latest --status
```

3. Run the server from this directory:

```bash
python3 serve.py
```

4. Open http://127.0.0.1:8765, type a query, submit. The server runs `firecrawl search "{query} site:amazon.com"` (limit 1), scrapes the top hit, parses markdown with the same parser that built `product.json`, and returns that JSON to the UI.

Do not put `FIRECRAWL_API_KEY` in `index.html` or commit it. If you need a key in CI, use the environment or `firecrawl login --api-key` locally.

## Rebuild `product.json`

If you already have markdown from a scrape:

```bash
python3 serve.py --parse path/to/page.md path/to/search.json --query "Play 5" -o product.json
```

## Limits you will see

- Amazon often hides the buy-box price (MAP). The card shows “See price in cart” plus any *New condition* price the markdown still leaked.
- The markdown is noisy. Coverage pills are honest about bullets and ASIN versus Q&A, variants, and add-to-cart (which wants an Amazon login; this demo never logs into Amazon).
- Keyless Firecrawl is rate-limited per IP. A free login is the path that works.

Scraping Amazon may conflict with Amazon’s conditions of use. This repo is a visualization of Firecrawl output on a scrape you run under your own account. Respect the sites you hit.

## License

MIT. See `LICENSE`.
