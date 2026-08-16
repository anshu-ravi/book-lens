# BookLens frontend

SvelteKit 2 + Svelte 5 (runes) + TypeScript, built as a static SPA with `@sveltejs/adapter-static`. No server-side rendering — the API is the only backend.

## Dev

```
npm install
npm run dev
```

Runs on `http://localhost:5173`. `/api/*` requests are proxied to `http://127.0.0.1:8000`, so run the Python API alongside it:

```
booklens serve
```

## Build

```
npm run build
```

Writes the static site to `build/`. Serve it with `booklens serve` (which serves the built SPA alongside the API) or any static file server, as long as unknown paths fall back to `index.html`.

## Type-check

```
npm run check
```
