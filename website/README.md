# kyanth.com

The landing page. Static HTML with inline CSS and one small script — no build
step, no dependencies, no framework.

## Deploying

Upload both of these to the web root, keeping the structure:

```
index.html
assets/
```

That is the whole deploy. It works on any static host — Netlify, Cloudflare
Pages, GitHub Pages, S3, or a plain directory behind nginx. No server-side
anything is required.

For GitHub Pages specifically, either publish this folder as the site source or
copy its two entries to the branch Pages serves from.

## The download button

The page ships with the download links pointing at
`github.com/austinbrown34/kyanth/releases/latest`, which always resolves to the
current release. On load, a script asks the GitHub API for that release and
rewrites the links to the `.dmg` asset directly, and fills in the version and
file size.

If that request fails — offline, rate-limited, JavaScript disabled — the links
still work, they just land on the releases page instead of starting a download.
Nothing on the page depends on the script running.

## Assets

| File | What it is |
|---|---|
| `assets/icon-512.png` etc. | the app icon, straight out of `assets/kyanth.iconset` |
| `assets/overlay-states.png` | four states of the dictation overlay |
| `assets/ui-setup.png` | the setup window |
| `assets/ui-shortcut.png` | Settings → Shortcut |
| `assets/ui-history.png` | Settings → History |

**The screenshots use written sample transcriptions, never real dictation
history.** They are rendered by driving the actual app UI against a synthetic
store, so they are honest screenshots of real windows without publishing
anything anyone actually said. Regenerating them by screenshotting a live
install would leak private history onto a public page.

All PNGs are palette-quantised — 4.2 MB of raw captures down to 268 KB with no
visible loss, since UI screenshots are flat colour and text.
