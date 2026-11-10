// Walk a frontend-slides deck the way upstream/frontend-slides-PKU
// scripts/test-steps.mjs does, and write one settled PNG per narration step.
//
// The submodule script is a one-shot with no exports, so this file repeats
// its contract instead of importing it: spoof navigator.webdriver (otherwise
// the engine forces every fragment visible for PDF export), open at
// 1920×1080, and advance with a single ArrowRight. Step 0 is the arrival
// state. The CSS fade is turned off at record time so each PNG is the
// settled frame; ffmpeg holds that frame for the narration.
//
//   node record-deck.mjs plan.json
// plan.json: { "deck": "/abs/deck.html", "shots": [{ "slide": 1, "step": 0, "png": "/abs/out.png" }] }

import { chromium } from 'playwright';
import { readFileSync, mkdirSync } from 'fs';
import { dirname } from 'path';
import { pathToFileURL } from 'url';

const plan = JSON.parse(readFileSync(process.argv[2], 'utf8'));

function fail(message, extra) {
  console.error(message);
  if (extra) console.error(JSON.stringify(extra));
  process.exit(1);
}

const browser = await chromium.launch({
  args: ['--disable-dev-shm-usage', '--disable-gpu'],
});
const page = await browser.newPage({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
});
page.on('pageerror', (err) => console.log('PAGEERROR', err.message));

// Playwright sets navigator.webdriver, and the engine treats that as PDF
// export (html.rv-instant forces every .st visible). Put the flag back
// before any page script runs, matching test-steps.mjs.
await page.addInitScript(() => {
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
});

await page.goto(pathToFileURL(plan.deck).href, {
  waitUntil: 'domcontentloaded',
  timeout: 30000,
});

await page.evaluate(() => {
  const scroller = document.querySelector('.slides-scroller');
  if (!scroller) throw new Error('no .slides-scroller — not a frontend-slides deck');
  const original = scroller.scrollTo.bind(scroller);
  scroller.scrollTo = (options) => {
    if (options && typeof options === 'object') {
      return original({ ...options, behavior: 'instant' });
    }
    return original(options);
  };
  const style = document.createElement('style');
  // Settled frame only. The 0.45s opacity fade is shorter than narration
  // and would make the hold time depend on wall-clock animation.
  style.textContent = [
    '.reveal, .st, .st.pop, .st .dot, .st .curvepath {',
    '  transition: none !important;',
    '  animation: none !important;',
    '}',
  ].join('\n');
  document.head.appendChild(style);
});

await Promise.race([
  page.evaluate(() => (document.fonts ? document.fonts.ready : Promise.resolve())),
  page.waitForTimeout(4000),
]);

await Promise.race([
  page.evaluate(async () => {
    const started = Date.now();
    while (Date.now() - started < 3000) {
      if (window.MathJax?.startup?.promise) {
        try { await window.MathJax.startup.promise; } catch { /* untypeset math is still a frame */ }
        return;
      }
      if (!document.getElementById('MathJax-script')) return;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  }),
  page.waitForTimeout(4000),
]);

await page.locator('body').click({ position: { x: 8, y: 8 } });

async function probe(slideNumber, step) {
  return page.evaluate(({ slideNumber, step }) => {
    const slides = [...document.querySelectorAll('.slide')];
    const index = slideNumber - 1;
    const slide = slides[index];
    const scroller = document.querySelector('.slides-scroller');
    if (!slide || !scroller) {
      return { ok: false, reason: 'missing slide or scroller', slideCount: slides.length };
    }
    const scrollOk = Math.abs(scroller.scrollTop - index * 1080) < 2;
    const visible = slide.classList.contains('visible');
    const mismatches = [];
    for (const el of slide.querySelectorAll('.st')) {
      const n = Number(el.dataset.st);
      const until = el.dataset.until;
      const should = n <= step && (until === undefined || until === '' || step <= Number(until));
      const on = el.classList.contains('on');
      if (on !== should) mismatches.push({ n, until: until ?? null, should, on });
    }
    return {
      ok: scrollOk && visible && mismatches.length === 0,
      scroll: scroller.scrollTop,
      scrollOk,
      visible,
      mismatches,
      slideCount: slides.length,
      on: slide.querySelectorAll('.st.on').length,
      tot: slide.querySelectorAll('.st').length,
    };
  }, { slideNumber, step });
}

async function settle(slideNumber) {
  const index = slideNumber - 1;
  await page.waitForFunction((target) => {
    const slides = document.querySelectorAll('.slide');
    const scroller = document.querySelector('.slides-scroller');
    return Boolean(
      slides[target]
      && slides[target].classList.contains('visible')
      && Math.abs(scroller.scrollTop - target * 1080) < 2,
    );
  }, index, { timeout: 5000 });
  await page.evaluate(() => new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  }));
}

for (let i = 0; i < plan.shots.length; i++) {
  const shot = plan.shots[i];
  if (i > 0) await page.keyboard.press('ArrowRight');
  try {
    await settle(shot.slide);
  } catch (err) {
    const state = await probe(shot.slide, shot.step);
    await browser.close();
    fail(`did not reach slide ${shot.slide} step ${shot.step}: ${err.message}`, state);
  }
  const state = await probe(shot.slide, shot.step);
  if (!state.ok) {
    await browser.close();
    fail(`slide ${shot.slide} step ${shot.step} does not match the engine`, { shot, state });
  }
  mkdirSync(dirname(shot.png), { recursive: true });
  await page.screenshot({ path: shot.png, fullPage: false });
  console.log(`shot ${i + 1}/${plan.shots.length} slide ${shot.slide} step ${shot.step}`);
}

await browser.close();
