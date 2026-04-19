"""Patch track-surface-spa.html with animation player controls.

Idempotent: running twice produces the same output.
"""
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parent.parent / "track-surface-spa.html"


def main() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    changed = False

    # 1. gripAnim mode button
    old_mode = '<button class="mode-btn active" data-mode="gripPhys">Grip Phys</button>'
    new_mode = (
        '<button class="mode-btn active" data-mode="gripPhys">Phys</button>\n'
        '    <button class="mode-btn" data-mode="gripAnim">Anim</button>'
    )
    if old_mode in html:
        html = html.replace(old_mode, new_mode)
        print("[OK] Added Grip Anim button")
        changed = True

    # 2. Lap Playback panel
    if 'id="lapSlider"' not in html:
        playback = """
  <h2>Lap Playback</h2>
  <div class="control-group">
    <div class="control-row"><label>Lap</label><span id="lapDisplay">---</span></div>
    <input type="range" id="lapSlider" min="0" max="0" value="0" style="width:100%;accent-color:#c9a84c">
    <div class="control-row">
      <button class="mode-btn" id="playBtn" style="flex:1">Play</button>
      <button class="mode-btn" id="stopBtn" style="flex:1">Stop</button>
    </div>
    <div class="control-row"><label>Speed</label><input type="range" id="animSpeed" min="1" max="8" value="2" step="1"><span id="animSpeedVal">2 fps</span></div>
  </div>

  <div class="driver-legend">"""
        if '  <div class="driver-legend">' in html:
            html = html.replace('  <div class="driver-legend">', playback, 1)
            print("[OK] Added Lap Playback panel")
            changed = True

    # 3. Animation state
    if "currentFrame:0" not in html:
        html = html.replace(
            "mode:'gripPhys'",
            "mode:'gripPhys', currentFrame:0, playing:false, animFps:2",
        )
        print("[OK] Added animation state")
        changed = True

    # 4. decodeGripAnimation helper before buildScene
    if "decodeGripAnimation" not in html:
        decoder = """
// Animated grip decoder — keeps bytes as Uint8Array, dequantizes on demand
let ANIM = null;
function decodeGripAnimation(enc) {
  if (!enc || !enc.base64_payload) return null;
  const bin = atob(enc.base64_payload);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return {
    bytes,
    shape_f: enc.shape_f,
    shape_m: enc.shape_m,
    shape_k: enc.shape_k,
    mu_min: enc.mu_min,
    mu_scale: enc.mu_scale,
    lap_numbers: enc.lap_numbers,
    lap_times_s: enc.lap_times_s,
    lookupMu(f, sIdx, nIdx) {
      if (f < 0 || f >= this.shape_f) return this.mu_min;
      if (sIdx < 0 || sIdx >= this.shape_m) return this.mu_min;
      if (nIdx < 0 || nIdx >= this.shape_k) return this.mu_min;
      const cells = this.shape_m * this.shape_k;
      return this.mu_min + this.mu_scale * this.bytes[f * cells + sIdx * this.shape_k + nIdx];
    },
  };
}
"""
        html = html.replace("function buildScene()", decoder + "\nfunction buildScene()", 1)
        print("[OK] Added ANIM decoder")
        changed = True

    # 5. Wire ANIM init in loadData
    old_load = (
        "document.getElementById('loadingMsg').style.display = 'none';\n"
        "    buildScene();"
    )
    new_load = (
        "document.getElementById('loadingMsg').style.display = 'none';\n"
        "    if (DATA.grip_animation) {\n"
        "      ANIM = decodeGripAnimation(DATA.grip_animation);\n"
        "      if (ANIM) {\n"
        "        document.getElementById('lapSlider').max = ANIM.shape_f - 1;\n"
        "        document.getElementById('lapDisplay').textContent = \n"
        "          '#' + ANIM.lap_numbers[0] + ' (' + ANIM.lap_times_s[0].toFixed(2) + 's)';\n"
        "      }\n"
        "    }\n"
        "    buildScene();"
    )
    if old_load in html and "ANIM = decodeGripAnimation" not in html:
        html = html.replace(old_load, new_load)
        print("[OK] Wired ANIM init")
        changed = True

    # 6. gripAnim color handler (inserted inside the grip branch block)
    anim_branch_marker = "state.mode === 'gripAnim'"
    if anim_branch_marker not in html:
        # Insert a branch before the final grip observation branch
        old_grip_branch = (
            "} else if(state.mode === 'grip') {\n"
            "        // Grip CEILING from the friction envelope"
        )
        new_grip_branch = (
            "} else if(state.mode === 'gripAnim') {\n"
            "        // ANIMATED per-wheel physics grip at the current frame\n"
            "        let mu = 1.0;\n"
            "        if(ANIM) {\n"
            "          const sFrac = i / n;\n"
            "          const sIdx = Math.min(ANIM.shape_m - 1, Math.max(0, Math.floor(sFrac * ANIM.shape_m)));\n"
            "          const nStep = 30.0 / ANIM.shape_k;\n"
            "          const nIdx = Math.min(ANIM.shape_k - 1, Math.max(0, Math.floor((offset + 15.0) / nStep)));\n"
            "          const rawMu = ANIM.lookupMu(state.currentFrame, sIdx, nIdx);\n"
            "          if(rawMu > 0.05) mu = rawMu;\n"
            "        }\n"
            "        col = gripColor(mu);\n"
            "      } else if(state.mode === 'grip') {\n"
            "        // Grip CEILING from the friction envelope"
        )
        if old_grip_branch in html:
            html = html.replace(old_grip_branch, new_grip_branch)
            print("[OK] Added gripAnim color handler")
            changed = True

    # 7. gripAnim legend case
    if "Grip μ — Lap " not in html:
        old_leg = (
            "if(state.mode==='gripPhys'){\n"
            "    bar.style.background='linear-gradient(to right,#1a1a2e,#3b82f6,#facc15,#22c55e,#aaffcc)';\n"
            "    t.textContent='Grip μ (physics, per-wheel)';lo.textContent='0.5';mi.textContent='1.0';hi.textContent='1.5+';\n"
            "  }else if(state.mode==='grip'){"
        )
        new_leg = (
            "if(state.mode==='gripPhys'){\n"
            "    bar.style.background='linear-gradient(to right,#1a1a2e,#3b82f6,#facc15,#22c55e,#aaffcc)';\n"
            "    t.textContent='Grip μ (physics, static)';lo.textContent='0.5';mi.textContent='1.0';hi.textContent='1.5+';\n"
            "  }else if(state.mode==='gripAnim'){\n"
            "    bar.style.background='linear-gradient(to right,#1a1a2e,#3b82f6,#facc15,#22c55e,#aaffcc)';\n"
            "    const labInfo = (ANIM ? ('#'+ANIM.lap_numbers[state.currentFrame]+' ('+ANIM.lap_times_s[state.currentFrame].toFixed(2)+'s)') : '---');\n"
            "    t.textContent='Grip μ — Lap '+labInfo;lo.textContent='0.5';mi.textContent='1.0';hi.textContent='1.5+';\n"
            "  }else if(state.mode==='grip'){"
        )
        if old_leg in html:
            html = html.replace(old_leg, new_leg)
            print("[OK] Added gripAnim legend")
            changed = True

    # 8. Player state machine
    if "animTimer = null" not in html:
        player = """
// Animation playback state machine
let animTimer = null;
function stepFrame() {
  if (!ANIM) return;
  state.currentFrame = (state.currentFrame + 1) % ANIM.shape_f;
  document.getElementById('lapSlider').value = state.currentFrame;
  document.getElementById('lapDisplay').textContent =
    '#' + ANIM.lap_numbers[state.currentFrame] + ' (' + ANIM.lap_times_s[state.currentFrame].toFixed(2) + 's)';
  if (state.mode === 'gripAnim') { buildScene(); updateLegend(); }
}
const btnPlay = document.getElementById('playBtn');
const btnStop = document.getElementById('stopBtn');
const lapSlider = document.getElementById('lapSlider');
const animSpeedEl = document.getElementById('animSpeed');
if (btnPlay) {
  btnPlay.addEventListener('click', () => {
    if (!ANIM) return;
    if (state.playing) {
      if (animTimer) clearInterval(animTimer);
      state.playing = false;
      btnPlay.textContent = 'Play';
    } else {
      state.playing = true;
      btnPlay.textContent = 'Pause';
      animTimer = setInterval(stepFrame, 1000 / state.animFps);
    }
  });
}
if (btnStop) {
  btnStop.addEventListener('click', () => {
    if (animTimer) clearInterval(animTimer);
    state.playing = false;
    state.currentFrame = 0;
    if (lapSlider) lapSlider.value = 0;
    if (btnPlay) btnPlay.textContent = 'Play';
    if (ANIM) {
      document.getElementById('lapDisplay').textContent =
        '#' + ANIM.lap_numbers[0] + ' (' + ANIM.lap_times_s[0].toFixed(2) + 's)';
    }
    if (state.mode === 'gripAnim') { buildScene(); updateLegend(); }
  });
}
if (lapSlider) {
  lapSlider.addEventListener('input', (e) => {
    state.currentFrame = parseInt(e.target.value, 10);
    if (ANIM) {
      document.getElementById('lapDisplay').textContent =
        '#' + ANIM.lap_numbers[state.currentFrame] + ' (' + ANIM.lap_times_s[state.currentFrame].toFixed(2) + 's)';
    }
    if (state.mode === 'gripAnim') { buildScene(); updateLegend(); }
  });
}
if (animSpeedEl) {
  animSpeedEl.addEventListener('input', (e) => {
    state.animFps = parseInt(e.target.value, 10);
    document.getElementById('animSpeedVal').textContent = state.animFps + ' fps';
    if (state.playing && animTimer) {
      clearInterval(animTimer);
      animTimer = setInterval(stepFrame, 1000 / state.animFps);
    }
  });
}
"""
        html = html.replace("animate();", player + "\nanimate();", 1)
        print("[OK] Added player state machine")
        changed = True

    if changed:
        HTML_PATH.write_text(html, encoding="utf-8")
    print(f"HTML size: {len(html) // 1024} KB")


if __name__ == "__main__":
    main()
