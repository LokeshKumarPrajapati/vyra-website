# Perfect Anime Character Improvement Plan

Goal: Make the Live2D character feel like a real anime girl with **1000s of emotions**, natural behavior, and no visual bugs (e.g. mouth always closed when not speaking).

---

## ✅ Phase 1: Critical Fixes (Done)

### 1.1 Mouth Always Closed When Not Speaking
- **Problem:** Mouth stayed open when the character was idle/listening/thinking.
- **Cause:** Lip-sync only ran a one-time “smooth close”; Live2D motions can keyframe mouth open, so it opened again.
- **Fix:** When `status !== 'speaking'`, run a **persistent** `requestAnimationFrame` loop that:
  - Decays `currentMouthValueRef` toward 0 every frame.
  - Calls `setParameterValueById(mouthParam, value)` every frame so we **override** motion-driven mouth.
  - Stops only when switching to speaking (cleanup cancels the loop).
- **Also:** When speaking, if `level <= 0.01` (no audio), use `targetValue = 0` so mouth stays closed during silent gaps.

---

## ✅ Phase 2: Emotion & Motion Scale (1000s of Emotions) — Done

### 2.1 Expand Emotion Taxonomy ✅
- **Frontend:** `emotionMotionMap.js` now has `getKeywordsForEmotion(emotion, intensity)`. High intensity (> 0.55) adds more expressive keywords (e.g. happy → sparkling, wandahoi; sad → cry, face_cry) so one emotion maps to many motion/face blends.
- **Facial params:** Already scale with `emotionIntensity` in `getEmotionFacialParams`.
- **Emotion detector:** Added more patterns: annoyed, excited, nervous, proud, melancholic, thrilled, awkward, jk, etc., mapped to existing emotions.

### 2.2 Use All Available Motions
- **Current:** `motionList.js` + `emotionMotionMap.js` cover 300+ motions; model has 381 motion groups. All listed motions are reachable via emotion keywords; “neutral” catches the rest.

### 2.3 Reduce Repetition and Increase Variety ✅
- **RECENT_MOTION_HISTORY_SIZE** increased to **12** (from 6) so we avoid repeating the same motion for longer.
- **Emotion-based timing:** `MIN_MOTION_DURATION` and next-motion delay vary by emotion: happy/playful/surprised/loving → faster (2.2s min, 3.5–6.5s delay); sad/sleepy/worried/thinking → slower (3s min, 5.5–9.5s delay). Feels more natural.

---

## Phase 3: Natural “Anime Girl” Behavior

### 3.1 Idle Behavior
- **Breathing:** Subtle loop (e.g. very small periodic change to chest/mouth or a dedicated “breathing” motion) so idle never looks frozen.
- **Micro-expressions:** Occasionally blend in very small, short face parameter tweaks (e.g. tiny smile, blink) at random intervals.
- **Blinking:** If the model supports blink parameters, drive them with a random blink rate (e.g. every 2–5 s) instead of only via motions.

### 3.2 Context-Aware Motion Choice
- **Speaking:** Keep current “calm” pool (nod, pose, tilthead, etc.) so body doesn’t overpower lip-sync; optionally bias by current emotion (e.g. “happy” speaking → slightly more “smile” in the pool).
- **Listening:** Prefer “thinking”, “curious”, “attentive” motions (look, nod, tilthead, think) and slightly shorter intervals so she feels reactive.
- **Thinking:** Prefer “serious”, “look”, “consider” motions; slightly longer holds for a “pondering” feel.
- **Idle:** Full emotion-driven pool; longer, more varied delays so it feels natural, not mechanical.

### 3.3 Smooth Transitions
- **Emotion changes:** Already blending facial params over ~1 s; ensure motion changes don’t clash (e.g. avoid switching from “cry” to “sparkling” in one step; optionally add a “transition” emotion or shorter blend).
- **Motion blending:** Rely on Live2D’s FadeIn/FadeOut; if needed, tune `FadeInTime`/`FadeOutTime` in model JSON for smoother handoffs.

### 3.4 Lip-Sync and Mouth
- **When speaking:** Keep current system (client playback + AnalyserNode → mouth parameter); ensure smoothing and gain feel good for the character’s art style.
- **When not speaking:** Rely on Phase 1 persistent “mouth closed” loop so mouth is **always** closed unless we’re actively driving it from audio.
- **Optional:** Add a tiny “mouth form” bias from emotion when idle (e.g. “happy” → very slight smile, “sad” → neutral or slight frown) via `mouthForm` in facial params, without opening the jaw.

---

## Phase 4: Technical Hygiene

### 4.1 Performance
- Single `requestAnimationFrame` loop per state (either “mouth closed” or “lip-sync”), properly cancelled on switch.
- Avoid creating new closures every frame; use refs for model, mouth param, and current value.
- Keep emotion/motion logic in a small number of modules (`HaruCharacter.jsx`, `emotionMotionMap.js`, `motionList.js`) so updates are easy.

### 4.2 Robustness
- If `mouthParameterRef.current` is null (model doesn’t expose mouth), disable lip-sync and mouth-closed loop gracefully (no errors, character still animates).
- If a motion name doesn’t exist in the model, `playMotionByName` already returns false; optionally log once per missing motion to aid debugging.

### 4.3 Configuration
- Consider a small config (e.g. `characterConfig.js`) for:
  - `RECENT_MOTION_HISTORY_SIZE`
  - `MIN_MOTION_DURATION` (idle / listening / thinking / speaking)
  - Mouth closed decay rate (0.82)
  - Lip-sync smoothing and gain
  So tuning doesn’t require editing core components.

---

## Phase 5: Future Enhancements (Optional)

- **Blink layer:** Dedicated blink timer and parameter (if supported by the model).
- **Breathing motion:** Optional idle “breathing” motion or parameter loop.
- **Sub-emotions:** Backend sends e.g. `[EMOTION:happy, sub:excited]` and frontend maps to an even more specific motion pool.
- **Reaction delay:** Short delay between “user spoke” / “model thinking” and motion change so reactions feel less instant and more natural.
- **Multiple models:** If you add more Live2D models, reuse the same emotion/motion map and mouth logic; only motion list and model path change.

---

## Summary Checklist

| Item | Status |
|------|--------|
| Mouth closed when not speaking (persistent loop) | ✅ Done |
| Mouth closed during silent parts of speech (level ≤ 0.01 → 0) | ✅ Done |
| Expand emotion taxonomy (intensity, compounds) | ✅ Done |
| Use all motions + keyword coverage | ✅ Done |
| Larger recent-motion history + emotion-based timing | ✅ Done |
| Idle breathing / micro-expressions / blink | 📋 Plan |
| Context-aware motion choice (listen/think/idle/speak) | 📋 Plan |
| Config file for tuning | 📋 Plan |

Implementing Phases 2–4 in small steps will get you to a character that feels like she has “1000s of emotions” and acts like a natural anime girl, with the mouth bug fixed.
