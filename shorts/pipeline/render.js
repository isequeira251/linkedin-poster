#!/usr/bin/env node
// Render every scene of a Short to webm via Playwright video recording.
// Usage: node shorts/pipeline/render.js <slug>
// Reads  shorts/videos/<slug>/script.json + shorts/out/<slug>/audio/durations.json
// Writes shorts/out/<slug>/scenes/scene_NN.webm   (vertical 1080x1920)

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const W = 1080, H = 1920;
const PAD_MS = 600; // visual tail after narration ends

async function main() {
  const slug = process.argv[2];
  if (!slug) { console.error('usage: render.js <slug>'); process.exit(1); }
  const root = path.resolve(__dirname, '..');
  const script = JSON.parse(fs.readFileSync(path.join(root, 'videos', slug, 'script.json'), 'utf8'));
  const durations = JSON.parse(fs.readFileSync(path.join(root, 'out', slug, 'audio', 'durations.json'), 'utf8'));
  const sceneDir = path.join(root, 'out', slug, 'scenes');
  fs.mkdirSync(sceneDir, { recursive: true });

  const browser = await chromium.launch();
  for (let i = 0; i < script.scenes.length; i++) {
    const scene = script.scenes[i];
    const tag = String(i).padStart(2, '0');
    const durMs = Math.round(durations[tag] * 1000) + PAD_MS;
    const ctx = await browser.newContext({
      viewport: { width: W, height: H },
      recordVideo: { dir: sceneDir, size: { width: W, height: H } },
    });
    const page = await ctx.newPage();
    await page.goto('file://' + path.join(root, 'player', 'scene_short.html'));
    const t0 = Date.now();
    await page.evaluate(
      ([spec, d]) => window.renderScene(spec, d),
      [scene, durMs]
    ).catch(e => { throw new Error(`scene ${tag} render failed: ${e.message}`); });
    // choreography may resolve early — hold the final frame until narration + pad elapses
    await page.waitForTimeout(Math.max(400, durMs - (Date.now() - t0)));
    const video = page.video();
    await ctx.close();
    const tmp = await video.path();
    fs.renameSync(tmp, path.join(sceneDir, `scene_${tag}.webm`));
    console.log(`rendered scene_${tag}.webm (${(durMs / 1000).toFixed(1)}s)`);
  }
  await browser.close();
}

main().catch(e => { console.error(e); process.exit(1); });
