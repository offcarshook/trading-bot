# ⚽ GAME BUILD PROMPT — "Strike 27" (original mobile football game)

> Paste everything below into your AI coding agent. It's written so the agent ships a **playable build fast** instead of over-planning.

---

## 0. Role & Rules for the Agent

You are a senior mobile game developer. Build an **original** 11v11 arcade-realistic football (soccer) game for mobile browsers, with the feel of modern console football games — but **all names, teams, players, logos, kits, menus, music and art must be original**. Do NOT use any FIFA/EA/club/league/real-player names, likenesses or trademarks.

**Speed rules (do not waste credits):**
- Ship a playable vertical slice FIRST (one match, two teams, full controls), then iterate.
- No long planning documents. Write code, run it, fix it.
- Don't ask questions that have a sensible default — pick the default and keep going.
- Keep the whole thing in one repo, zero paid assets, everything procedural or free-license (CC0).
- Commit after every milestone.

---

## 1. Tech Stack (fixed — don't debate it)

| Area | Choice |
|---|---|
| Engine | **Three.js** (r160+) + **Vite** + **TypeScript** |
| Physics | Custom lightweight ball physics (gravity, drag, Magnus spin, bounce, ground friction). No heavy physics engine. |
| Models | Low-poly **skinned glTF humanoids** (CC0, e.g. Quaternius / Mixamo-style rigs) with animation blending. Fallback: procedural capsule players if assets fail to load. |
| Input | Pointer Events (multi-touch), keyboard + gamepad as fallback for desktop testing |
| Audio | Web Audio API, procedural crowd noise + whistle + kick SFX |
| Target | 60 FPS on mid-range phones (e.g. 2022 Android), landscape only, PWA installable |

---

## 2. Core Goal of the Game 🎯

- Full 11v11 match, default **6-minute halves** (configurable 3/6/10), with kickoff, halftime side switch, full time.
- Win by scoring more goals. Draw in knockout → extra time → penalty shootout.
- Modes for v1: **Quick Match**, **Penalty Shootout**, **Skill Training** (free play with cones/targets).
- Modes for v2 (stretch): short tournament (8 teams, bracket), local 2-player on one tablet (split controls).

---

## 3. Mobile Control System (the most important part) 📱

Layout in landscape, all elements semi-transparent, resizable and repositionable in Settings.

### Left side — Virtual Joystick
- **Floating joystick**: appears wherever the left thumb touches in the left 40% of the screen.
- Analog: small push = jog, full push = run. Dead zone 10%.
- Direction is **camera-relative**, smoothed (no jitter), 8-direction snap OFF by default.

### Right side — Action Buttons
**Attacking (ball possessed):**
| Button | Tap | Hold | Swipe on button |
|---|---|---|---|
| **Pass** | Ground pass to best target in stick direction | Longer/stronger pass (power bar) | — |
| **Through** | Through ball into space | Lofted through ball | — |
| **Shoot** | Placed finesse shot | Power shot (power bar, over-charge = skied) | Swipe up = chip, swipe curve = curled shot |
| **Sprint** | — | Sprint (drains stamina) | — |
| **Skill** | Quick skill (feint/step-over) | — | Swipe direction = different skill move (roulette, drag-back, heel flick, elastico) |
| **Cross/Lob** | Cross from wide areas, otherwise lob pass | Driven cross | — |

**Defending (no possession):**
| Button | Action |
|---|---|
| **Switch** | Change to player nearest ball (or the one the stick points to) |
| **Press/Jockey** | Hold = contain & stay goal-side; teammate press on second button |
| **Tackle** | Standing tackle; double-tap = slide tackle (risk of foul/card) |
| **Sprint** | Same as attack |

### Control Feel Requirements
- Button presses are **buffered for 150 ms** so inputs never feel "eaten".
- Haptic vibration (`navigator.vibrate`) on shot, tackle, goal.
- Optional **Assist level**: Casual (auto-sprint, auto-switch, aim assist) / Pro (manual everything).
- Contextual button labels change instantly between attack/defense.
- Big touch targets (min 64px), never covered by the HUD.

---

## 4. Passing System 🎯➡️

- **Target selection**: score every teammate by `angle to stick direction (weight 0.5) + distance (0.2) + openness / interception risk (0.3)`. Pick highest. No stick input → pass toward the player in facing direction.
- **Pass types**: ground, driven, lofted, through-ball (leads the receiver into space), cross, back-heel (skill).
- **Power**: tap = auto power, hold = manual power bar on button.
- **Error model**: pass accuracy depends on player rating, pressure (nearest defender distance), body angle, and whether weak foot is used. Bad conditions = slight angle/power error.
- **Receiving**: receiver runs to meet the ball, first touch depends on ball speed + rating; heavy touch can be stolen.
- **One-touch passing**: pressing Pass before the ball arrives queues a first-time pass.
- **Give-and-go**: Pass then immediately Through again → passer makes a forward run for the return.
- Interceptions are physical: ball path is tested against defenders' reach every frame.

---

## 5. Camera System 🎥

- Default: **Broadcast cam** — high side view, smoothly follows the ball with look-ahead in the attack direction, auto zoom out when ball is far up/long ball.
- Alternative cams in settings: **Tele-Broadcast** (tighter), **Co-op** (wider), **Pro/Behind-player** (low, behind controlled player).
- Smoothing: critically-damped spring, no jerky snapping. Height & zoom adjustable sliders.
- Cinematic cuts: goal celebration replay (last 6 s re-simulated from recorded states), corner/free-kick close-up, penalty behind-the-taker view.
- Camera never clips through stands; always keeps the controlled player + ball on screen.

---

## 6. Players, Models & Animation 🏃

- Each player: skinned 3D model, team kit color (procedurally tinted texture), number on back, skin/hair variations.
- Animation state machine with **blend trees**: idle, jog, run, sprint, turn (90/180), dribble, pass (short/long), shoot (finesse/power), tackle, slide, header, volley, goalkeeper dive (left/right/high/low), celebration (3+ variations), fall/stumble.
- **Root motion OFF**; movement is physics-driven with animation speed matched to velocity (no foot sliding visible at normal speeds).
- Ball attaches near the dribbling foot with soft physics (ball pushes ahead at sprint = easier to lose).
- **Player attributes** (0–99): pace, shooting, passing, dribbling, defending, physical, stamina, plus GK stats. Overall rating shown on cards.
- Stamina drains with sprint; tired players are slower and less accurate.

---

## 7. AI 🧠

- **Team shape**: formation-based (4-3-3, 4-4-2, 3-5-2 selectable). Each player has a home position that shifts with ball position and attack/defend phase.
- **Attacking AI**: off-ball runs into space, overlapping fullbacks, striker runs on defender's shoulder (offside-aware).
- **Defending AI**: press the ball carrier with 1–2 players, cover passing lanes, hold a defensive line, step up to play offside.
- **Goalkeeper**: positions on the ball-goal line, reacts with delay based on rating, dives, catches/parries, sweeps through balls, distributes (throw/kick).
- Difficulty levels: Beginner / Amateur / Pro / Legend (reaction time, pass accuracy, pressing intensity).
- Use utility scoring + simple state machines. Run AI decisions at 10 Hz, movement at 60 Hz (performance!).

---

## 8. Rules & Match Flow 📏

- Throw-ins, goal kicks, corners, free kicks, penalties, offside, fouls, yellow/red cards, advantage.
- Set pieces: aim arrow + power + curl (swipe) for free kicks and corners.
- Penalty: aim with joystick, power with hold; keeper: swipe to dive.
- Referee logic as a simple rules engine (no visible referee model needed in v1).
- Scoreboard + timer top-left, mini radar map bottom-center (toggleable).

---

## 9. Performance Budget ⚡ (non-negotiable)

- ≤ 150 draw calls, ≤ 300k triangles on screen, players use instanced materials and LODs (3 levels).
- Shadows: one directional light, small shadow map (1024), blob shadows on low setting.
- Graphics presets: Low / Medium / High, auto-detected on first launch.
- Fixed 60 Hz physics step, interpolated rendering.
- Initial load < 10 MB, < 5 s on 4G. Lazy-load stadium crowd.
- No garbage in the hot loop (reuse vectors).

---

## 10. Presentation & UI 🎨

- Original stadium (procedural stands, animated low-poly crowd via instancing, floodlights, day/night).
- Main menu → Team select (16 fictional teams with original names, crests generated from shapes + colors) → Kit select → Match.
- Pause menu: resume, controls layout editor, camera settings, substitutions, formation change, quit.
- Goal: slow-mo + replay + scorer name banner + celebration animation.
- Original synth/drums menu music (procedural or CC0).

---

## 11. Project Structure

```
/src
  main.ts            # bootstrap, game loop
  core/              # loop, time, events, input buffer
  input/             # joystick, buttons, gestures, gamepad
  physics/           # ball physics, collisions
  players/           # player entity, attributes, animation controller
  ai/                # team tactics, player brains, goalkeeper
  match/             # rules engine, set pieces, match state
  camera/            # camera rigs & cinematics
  render/            # scene, stadium, crowd, LOD
  ui/                # HUD, menus (plain HTML/CSS overlay)
  audio/
/public/assets       # CC0 models, textures, sounds
```

---

## 12. Milestones (build in THIS order, commit each)

1. **Pitch + ball physics + one controllable player** with joystick & sprint.
2. **Pass / shoot / tackle buttons** + passing target system + broadcast camera.
3. **22 players, formations, basic AI, goalkeepers** → full playable match with score & timer. ✅ *Vertical slice — must be playable here.*
4. Rules (out of play, corners, fouls, offside) + set pieces.
5. Skinned models + animation blending + kits.
6. Skill moves, through balls, one-touch, give-and-go, crosses/headers.
7. Menus, team select, settings, control layout editor, graphics presets.
8. Replays, celebrations, audio, crowd, polish, PWA.

## 13. Definition of Done ✅
- Launch on a phone browser, pick teams, play a full match at 60 FPS with joystick + buttons.
- Passing feels responsive and chooses the right teammate >90% of the time.
- AI defends, attacks and scores; keeper saves realistic shots.
- No console errors, `npm run build` passes, README explains how to run (`npm i && npm run dev`).
