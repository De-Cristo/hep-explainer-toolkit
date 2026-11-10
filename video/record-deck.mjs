// Walk a frontend-slides deck the way upstream/frontend-slides-PKU
// scripts/test-steps.mjs does.
//
// The submodule script is a one-shot with no exports, so this file repeats
// its contract: spoof navigator.webdriver (otherwise the engine forces every
// fragment visible for PDF export), open at 1920×1080, and advance with a
// single ArrowRight. Step 0 is the arrival state.
//
// mode "video": Playwright recordVideo, holding each step for holdMs. The
// hold budget includes the time spent advancing, so the on-screen time is
// the measured audio duration rather than audio-plus-navigation. Prints
// LEAD_MS and VIDEO. Exits non-zero if the browser dies.
// mode "stills": one PNG per step. A dead browser retries from the last
// finished PNG instead of aborting the whole deck.
//
//   node record-deck.mjs plan.json

import { chromium } from 'playwright';
import { mkdirSync, statSync, writeFileSync } from 'fs';
import { dirname } from 'path';
import { pathToFileURL } from 'url';
import { readFileSync } from 'fs';

const plan = JSON.parse(readFileSync(process.argv[2], 'utf8'));

// recordVideo writes a 0-byte webm until the browser context is closed.
// A SIGKILL never reaches this handler; the parent sends SIGTERM first.
const active = { browser: null, context: null, closing: false };

function playwrightLaunchOptions() {
  const executablePath = chromium.executablePath();
  if (
    executablePath === '/usr/bin/google-chrome'
    || executablePath === '/usr/bin/google-chrome-stable'
    || executablePath.includes('google-chrome')
  ) {
    fail(
      `refusing system Chrome at ${executablePath}. `
      + 'Install Playwright\'s Chromium: npx --prefix video playwright install chromium',
    );
  }
  console.log(`BROWSER ${executablePath}`);
  return {
    executablePath,
    args: ['--disable-dev-shm-usage', '--disable-gpu'],
  };
}

async function closeActive() {
  if (active.closing) return;
  active.closing = true;
  const context = active.context;
  const browser = active.browser;
  active.context = null;
  active.browser = null;
  if (context) await context.close().catch(() => {});
  if (browser) await browser.close().catch(() => {});
  active.closing = false;
}

process.on('SIGTERM', () => {
  console.error('SIGNAL SIGTERM');
  closeActive().finally(() => process.exit(1));
});
process.on('SIGINT', () => {
  console.error('SIGNAL SIGINT');
  closeActive().finally(() => process.exit(1));
});

function fail(message, extra) {
  console.error(message);
  if (extra) console.error(JSON.stringify(extra));
  process.exit(1);
}

function pngReady(file) {
  try {
    return statSync(file).size > 8000;
  } catch {
    return false;
  }
}

async function waitContentReady(page) {
  await page.evaluate(async () => {
    if (document.fonts) await document.fonts.ready;
    const images = [...document.images];
    await Promise.all(images.map(async (img) => {
      if (!img.complete) {
        await new Promise((resolve) => {
          img.addEventListener('load', resolve, { once: true });
          img.addEventListener('error', resolve, { once: true });
        });
      }
      if (typeof img.decode === 'function') {
        await img.decode().catch(() => {});
      }
    }));
    if (window.MathJax?.startup?.promise) {
      await window.MathJax.startup.promise.catch(() => {});
    }
    if (window.hepContentReady && typeof window.hepContentReady.then === 'function') {
      await Promise.race([
        window.hepContentReady,
        new Promise((resolve) => setTimeout(resolve, 5000)),
      ]);
    }
    await new Promise((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(resolve));
    });
    document.documentElement.dataset.hepExplainerReady = 'true';
  });
}

async function qualityProbe(page, slideNumber, step) {
  return page.evaluate(({ slideNumber, step }) => {
    const slide = [...document.querySelectorAll('.slide')][slideNumber - 1];
    if (!slide) return { slide: slideNumber, step, errors: ['missing slide'], overflow: [], brokenImages: [] };
    const slideRect = slide.getBoundingClientRect();
    const visible = (el) => {
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) > 0.01
        && rect.width > 0 && rect.height > 0;
    };
    const brokenImages = [...slide.querySelectorAll('img')]
      .filter((img) => visible(img) && (!img.complete || img.naturalWidth === 0))
      .map((img) => img.getAttribute('src') || '(image without src)');
    const selectors = [
      'img', 'svg', 'canvas', 'video',
      '.slide-content > *', '.left-col > *', '.right-col > *',
      '.two-col > *', '.dual-layout > *',
    ].join(',');
    const overflow = [];
    for (const el of slide.querySelectorAll(selectors)) {
      if (!visible(el)) continue;
      const rect = el.getBoundingClientRect();
      const tolerance = 2;
      if (
        rect.left < slideRect.left - tolerance
        || rect.top < slideRect.top - tolerance
        || rect.right > slideRect.right + tolerance
        || rect.bottom > slideRect.bottom + tolerance
      ) {
        overflow.push({
          tag: el.tagName.toLowerCase(),
          class: el.className?.baseVal ?? el.className ?? '',
          left: Math.round(rect.left - slideRect.left),
          top: Math.round(rect.top - slideRect.top),
          right: Math.round(rect.right - slideRect.left),
          bottom: Math.round(rect.bottom - slideRect.top),
        });
      }
    }
    return {
      slide: slideNumber,
      step,
      ready: document.documentElement.dataset.hepExplainerReady === 'true',
      brokenImages,
      overflow,
      errors: [],
    };
  }, { slideNumber, step });
}

async function openDeck(browser) {
  const page = await browser.newPage({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
  });
  page.on('pageerror', (err) => console.log('PAGEERROR', err.message));
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
    style.textContent = [
      '.reveal, .st, .st.pop, .st .dot, .st .curvepath {',
      '  transition: none !important;',
      '  animation: none !important;',
      '}',
    ].join('\n');
    document.head.appendChild(style);
  });
  await waitContentReady(page);
  await page.locator('body').click({ position: { x: 8, y: 8 } });
  return page;
}

function probe(page, slideNumber, step) {
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
    };
  }, { slideNumber, step });
}

async function settle(page, slideNumber) {
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

async function advanceTo(page, index) {
  for (let k = 0; k < index; k++) {
    await page.keyboard.press('ArrowRight');
    await settle(page, plan.shots[k + 1].slide);
  }
  await settle(page, plan.shots[index].slide);
  const state = await probe(page, plan.shots[index].slide, plan.shots[index].step);
  if (!state.ok) {
    throw new Error(`slide ${plan.shots[index].slide} step ${plan.shots[index].step} mismatch ${JSON.stringify(state)}`);
  }
}

async function captureStills() {
  let next = 0;
  const qaRows = [];
  const writeQa = () => {
    if (plan.qaPath) writeFileSync(plan.qaPath, JSON.stringify({ deck: plan.deck, states: qaRows.filter(Boolean) }, null, 2));
  };
  for (let attempt = 1; attempt <= 3 && next < plan.shots.length; attempt++) {
    while (next < plan.shots.length && pngReady(plan.shots[next].png)) next += 1;
    if (next >= plan.shots.length) { writeQa(); return; }
    let browser;
    try {
      browser = await chromium.launch(playwrightLaunchOptions());
      active.browser = browser;
      browser.on('disconnected', () => console.error('BROWSER_DISCONNECTED'));
      const page = await openDeck(browser);
      await advanceTo(page, next);
      for (let i = next; i < plan.shots.length; i++) {
        if (i !== next) {
          await page.keyboard.press('ArrowRight');
          await settle(page, plan.shots[i].slide);
          const state = await probe(page, plan.shots[i].slide, plan.shots[i].step);
          if (!state.ok) {
            throw new Error(`slide ${plan.shots[i].slide} step ${plan.shots[i].step} mismatch ${JSON.stringify(state)}`);
          }
        }
        mkdirSync(dirname(plan.shots[i].png), { recursive: true });
        await page.screenshot({ path: plan.shots[i].png, fullPage: false });
        if (!pngReady(plan.shots[i].png)) throw new Error(`screenshot too small: ${plan.shots[i].png}`);
        qaRows[i] = await qualityProbe(page, plan.shots[i].slide, plan.shots[i].step);
        console.log(`shot ${i + 1}/${plan.shots.length} slide ${plan.shots[i].slide} step ${plan.shots[i].step}`);
        next = i + 1;
      }
    } catch (err) {
      console.error(`stills attempt ${attempt} failed at shot ${next + 1}: ${err.message}`);
      if (attempt === 3) fail(`per-step screenshots aborted: ${err.message}`);
    } finally {
      await closeActive();
    }
  }
  writeQa();
}

async function captureVideo() {
  const browser = await chromium.launch(playwrightLaunchOptions());
  active.browser = browser;
  browser.on('disconnected', () => console.error('BROWSER_DISCONNECTED'));
  const t0 = Date.now();
  let context;
  try {
    context = await browser.newContext({
      viewport: { width: 1920, height: 1080 },
      recordVideo: { dir: plan.videoDir, size: { width: 1920, height: 1080 } },
    });
    active.context = context;
    const page = await context.newPage();
    page.on('pageerror', (err) => console.log('PAGEERROR', err.message));
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
    });
    await waitContentReady(page);
    await page.locator('body').click({ position: { x: 8, y: 8 } });
    await settle(page, plan.shots[0].slide);
    const lead = Date.now() - t0;
    console.log(`LEAD_MS ${lead}`);
    for (let i = 0; i < plan.shots.length; i++) {
      const start = Date.now();
      if (i > 0) {
        await page.keyboard.press('ArrowRight');
        await settle(page, plan.shots[i].slide);
      }
      const remain = Math.max(0, plan.shots[i].holdMs - (Date.now() - start));
      if (remain > 0) await page.waitForTimeout(remain);
    }
    const video = page.video();
    // Playwright finalizes the webm only when the context closes. Closing
    // here, and again in finally, is what keeps a killed run from leaving
    // a 0-byte file when the signal is one we can still handle.
    await context.close();
    active.context = null;
    context = null;
    const file = await video.path();
    console.log(`VIDEO ${file}`);
  } finally {
    if (context) {
      await context.close().catch(() => {});
      active.context = null;
      context = null;
    }
    await closeActive();
  }
}

if (plan.mode === 'video') {
  await captureVideo();
} else if (plan.mode === 'stills') {
  await captureStills();
} else {
  fail(`unknown recorder mode ${plan.mode}`);
}
