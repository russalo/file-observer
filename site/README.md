# site/ — the file-observer.russalo.com landing page

A single static page. **No app server, no build step, no JS** — `index.html`
plus its own copy of the brand assets under `assets/`. Serve the directory as-is.

## Serving (infra / tailnet)

Point `file-observer.russalo.com` at this directory with a static file server.
With the existing Caddy reverse proxy that's roughly:

```caddy
file-observer.russalo.com {
    root * /path/to/file-observer/site
    file_server
    encode gzip
}
```

DNS (`file-observer.russalo.com`), the cert, and the Caddy vhost are infra —
handled on the tailnet side, not from this repo.

## Why it lives here

The page's source belongs with the project, not in the blog repo, so it stays
in sync with the canonical docs and there's no cross-project coupling. The page
**links out** to the GitHub tutorial / examples / schema rather than duplicating
them — the one rule is *never hand-maintain a second copy of the docs that can
drift.*

## Assets

`assets/{logo,pipeline-diagram,og-card,favicon}.png` are copies of the brand
files in `../docs/assets/`. They're stable (the brand isn't version-bearing), so
a copy is fine. If the brand changes, re-copy from `../docs/assets/`.

## Deliberately version-agnostic

No version number anywhere on the page (`pip install file-observer`, not a
pinned version), so a release never requires a page edit. Same drift-avoidance
discipline as the rest of the docs.
