# Strike 27 ⚽

An original 11v11 football game for mobile browsers, built with Three.js.

## Play it
- Open `index.html` in a browser (phone in landscape works best), or serve the folder: `npx serve .`
- To host it for free, turn on **GitHub Pages** for this branch (Settings → Pages → deploy from branch, root folder).

## Controls
| | Attacking | Defending |
|---|---|---|
| Left thumb (anywhere) | Move, push to the edge to sprint | Move |
| PASS / J | Instant ground pass (auto-cross from wide areas) | Switch player |
| THRU / L | Through ball | Hold: press the ball carrier (a teammate joins) |
| LOB / U | Lofted long ball | Slide tackle |
| SHOOT / K | Tap: finesse curler · Hold: power (past the line skies it) | Tackle · double-tap: slide |
| SKILL / I | Feint past a defender | Hold: contain |
| SUBS | Substitutions (5 per match, made at the next stoppage) | |
| SPRINT / Shift | Sprint | Sprint |

## Files
- `index.html` – the playable game (single file, built)
- `game/strike27.html` – same game as a page fragment
- `src/` – the source: `head.html`, `style.css`, `shell.html` and `js/` (one file per system: scene, player model, animation rig, AI, simulation, set pieces, officials, HUD…)
- `build.mjs` – run `node build.mjs` after editing `src/` to rebuild both pages
- `docs/REPORT.md` – what the latest update changed, how it was tested and what is still missing
- `PROMPT.md` – the original build spec
