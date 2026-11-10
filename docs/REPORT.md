# Strike 27 — player realism update: what was done, what was not

This covers the pass that replaced the block-figure players. It follows the brief's rule of technical honesty:
nothing below is claimed unless it is in the code and was run.

## 1. Implementation report

| Area | Before | Now |
|---|---|---|
| Player body | 10 separate boxes per player | One skinned mesh with 17 bones (hips, spine, chest, neck, head, shoulders, elbows, wrists, hips, knees, ankles), rounded shoulders, knees and elbows that bend smoothly |
| Face and head | Plain sphere | Shaped head (jaw, cheekbones, brow, nose, lips, chin, ears) with a painted face: eyes, brows, mouth, shading, four beard types |
| Hair | Half sphere | Eight styles (short, crop, curly, afro, long, buzz, bald, bun) in seven colours, fitted to the head shape |
| Kits | Flat team colour | Painted per player: six club designs (panels, pinstripes, chest band, stripes, halves, sash), collar, crest, name and number on the back, number on chest and shorts, sock hoops, eight boot colours, keeper kit with gloves, referee kit |
| Identity | Everyone identical | Each player has their own skin tone, hair, beard, eye colour, boots, height, build and preferred foot; defenders and keepers are taller, wingers smaller. Substitutes come on with their own look |
| Running | Legs swinging like pendulums | Stride cycle with hip swing, knee fold on the recovery, stance flex, toe-off, arm swing with elbows folding as pace rises, body lean, hip and shoulder counter-rotation. Stride length and rate change from walk to sprint. Feet are grounded: the lower foot sets hip height |
| Other movement | None | Side-stepping, back-pedalling, ready stance for defenders and keepers, breathing and weight shift when standing, head turns to follow the ball |
| Kicking | Ball left instantly, leg flicked afterwards | Backswing, then the ball leaves on the frame the boot arrives, then follow-through. Holding SHOOT draws the leg back while you hold. The leg's reach is taken from where the ball really is. Passes use a side-foot shape, shots and long balls a full swing |
| Other actions | Body tilt | Slide tackle, standing-tackle lunge, first-touch cushion, feint, header jump, keeper dive (crouch, launch, land, get up) at the height of the shot, keeper holding and throwing, throw-in, wall stance, three celebrations, stumble, referee card and flag |
| Shadows | Dark blob | Real cast shadows from players and ball (Medium and High), following the camera and snapped to avoid shimmer; blob kept as soft contact shade |
| Ball | Oversized | Scaled to match the new bodies |
| Replays | Stored 8 values per player | Store the full animation state (29 values), so replays show the same poses that happened |
| Graphics settings | None | Low / Medium / High in the pause menu, picked automatically on first launch, plus automatic resolution scaling when frames run slow |
| Project layout | One 1,660-line page | `src/` with 25 ordered source files per system and `build.mjs` (joins them, syntax-checks, writes both pages) |

Everything that existed before still works: set pieces, referee, cards, offside, advantage, substitutions, pressing, fitness, AI.

## 2. Technical report

- **Engine:** Three.js r160 in the browser, no build dependencies beyond Node for `build.mjs`. No downloaded models, textures or animation clips: geometry, textures and poses are generated in code.
- **New files:** `src/js/05-config.js` (tunable numbers: graphics presets, kick timings, gait values), `30-model.js` (body and hair geometry, kit and face painter), `32-rig.js` (pose computation, grounding, blending), `34-players.js`.
- **Changed files:** `20-scene.js` (shadow light), `52-ballcontrol.js` and `80-ai.js` and `70-input.js` (kick wind-up), `84-sim.js` (stride rate, direction of travel), `56-officials.js`, `54-squads.js`, `66-replay.js`, `90-sync.js`, `96-menu.js`, `99-main.js`.
- **How animation works:** there are no clips. Each frame a pose (30 joint values) is computed from the player's real state and blended towards; the kicking leg blends almost instantly so contact is on time.
- **Kick timing** (`CFG.kick`): your pass 0.07 s, your lob 0.09 s, your shot 0.06 s after release, AI pass 0.12 s, AI shot 0.21 s. A tackle during the wind-up cancels the kick.
- **Measured cost** (software renderer, 844×390, mid-match): 79 draw calls and about 175,000 triangles per frame including the shadow pass. The old block players alone were about 220 draw calls.
- **Technical debt:** the source files still share one scope rather than being true modules; most gameplay numbers outside `05-config.js` are still inline.

## 3. Testing report

All run in headless Chromium against the built page.

| Test | Result |
|---|---|
| Build and syntax check | Pass |
| 6 simulated minutes AI v AI | Pass, no errors, no stuck restarts |
| Full match with halves, fitness and AI substitutions | Pass |
| Every set piece 30 times each | Pass. Penalties scored 27 of 30, direct free kicks 2 of 30, corners 0 of 30, throw-ins straight out 0 of 30 |
| Offside, advantage, red card, second yellow, set pieces with 9 players, substitution | Pass |
| Goal → celebration → replay → kick-off | Pass |
| Graphics switch Low/Medium/High mid-match | Pass |
| Close-up screenshots of standing, sprinting, kicking, sliding, diving players and faces | Checked by eye and corrected (proportions, shorts, hem, nose, ears) |

**Not verified:** nothing was run on a real phone, so frame rate, touch feel and heat are unmeasured. Goal kicks went straight out of play 7 times in 30 in the last run, which is higher than the earlier build (5 in 40) and not yet investigated.

## 4. Known limitations

- **Not photoreal and not motion capture.** Players are stylised procedural figures. Faces are painted textures on a shaped head; hands are mittens without fingers.
- **No cloth simulation.** Kits do not flap or fold.
- **Feet can slide slightly**, most visibly on the planted leg during a kick taken at a sprint.
- **Shoulders** show a crease where the sleeve meets the shirt when the arm is raised.
- **Not done from the brief:** pitch grass detail, stadium rebuild, animated crowd beyond the goal jump, deforming goal nets, day/dusk lighting, expanded player attributes and movement profiles, first-touch errors, chip-shot swipe, extra match statistics, stoppage time, control-layout editor, camera sliders, pre-match presentation, tactical AI additions (overlaps, box runs, marking), spatial audio. Still missing from earlier: teams do not change ends at half-time.
