#!/usr/bin/env python3
"""Check that a natively rendered page carries the same nav as a proxied one.

Usage: check_nav_parity.py [native_url] [proxied_url] [out_dir]
Defaults: https://epic-devcloud.org/prod/mcp/ against /prod/about/.
Signs in with SWF_REMOTE_CLAUDE_USER / SWF_REMOTE_CLAUDE_PASSWORD, loads both
pages, and compares the nav geometry: the nav box, its computed background
and padding, every top-level item's text and rectangle, and the first
dropdown's opened item rectangles. Saves a screenshot of each nav strip, one
with the dropdown open. Exit status 1 on any difference above half a pixel.
Run with the playwright wrapper: /home/admin/tools/playwright/python.
"""
import os
import sys

from playwright.sync_api import sync_playwright

native = sys.argv[1] if len(sys.argv) > 1 else 'https://epic-devcloud.org/prod/mcp/'
proxied = sys.argv[2] if len(sys.argv) > 2 else 'https://epic-devcloud.org/prod/about/'
out_dir = sys.argv[3] if len(sys.argv) > 3 else '.'
user, password = os.environ['SWF_REMOTE_CLAUDE_USER'], os.environ['SWF_REMOTE_CLAUDE_PASSWORD']
TOL = 0.5

MEASURE = '''() => {
  const nav = document.querySelector('nav');
  const r = e => { const b = e.getBoundingClientRect(); return [b.x, b.y, b.width, b.height].map(v => Math.round(v * 10) / 10); };
  const cs = getComputedStyle(nav);
  const items = [];
  for (const el of nav.children) {
    if (!(el.offsetWidth || el.offsetHeight) && !el.classList.contains('nav-mode')) continue;
    const kids = el.classList.contains('nav-mode') ? [...el.children] : [el];
    for (const k of kids) {
      const label = (k.querySelector('.dropbtn') || k).innerText.trim().replace(/\\s+/g, ' ') || k.className;
      items.push([label, r(k)]);
    }
  }
  return {nav: r(nav), background: cs.backgroundColor, padding: cs.padding, gap: cs.gap, items};
}'''

OPEN_FIRST = '''() => {
  const dd = document.querySelector('nav .nav-production .dropdown') || document.querySelector('nav .dropdown');
  const c = dd.querySelector('.dropdown-content'); c.style.display = 'block';
  const r = e => { const b = e.getBoundingClientRect(); return [b.x, b.y, b.width, b.height].map(v => Math.round(v * 10) / 10); };
  return [...c.querySelectorAll('a')].map(a => [a.innerText.trim(), r(a), getComputedStyle(a).padding]);
}'''


def diff(label, a, b):
    """Print and count differences between two measurements."""
    bad = 0
    if isinstance(a, list) and a and isinstance(a[0], (int, float)):
        d = [abs(x - y) for x, y in zip(a, b)]
        if len(a) != len(b) or max(d) > TOL:
            print(f'  DIFF {label}: {a} vs {b}'); bad += 1
    elif isinstance(a, list):
        if len(a) != len(b):
            print(f'  DIFF {label}: {len(a)} vs {len(b)} entries'); bad += 1
        for i, (x, y) in enumerate(zip(a, b)):
            bad += diff(f'{label}[{i}]', x, y)
    elif isinstance(a, dict):
        for k in a:
            bad += diff(f'{label}.{k}', a[k], b.get(k))
    elif a != b:
        print(f'  DIFF {label}: {a!r} vs {b!r}'); bad += 1
    return bad


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={'width': 1600, 'height': 900})
    page = ctx.new_page()
    page.goto('https://epic-devcloud.org/prod/accounts/login/', wait_until='networkidle')
    page.fill('input[name=username]', user)
    page.fill('input[name=password]', password)
    page.click('form:has(input[name=password]) button[type=submit]')
    page.wait_for_load_state('networkidle')
    signed_in = page.locator('nav .nav-auth').inner_text()
    if user not in signed_in:
        sys.exit(f'sign-in failed: nav auth block reads {signed_in!r}')
    results = {}
    for name, url in (('native', native), ('proxied', proxied)):
        page.goto(url, wait_until='networkidle')
        if page.url != url:
            sys.exit(f'{name}: {url} landed on {page.url}')
        if name == 'proxied' and 'Built at' not in page.inner_text('main'):
            sys.exit(f'{name}: {url} shows no monitor build line, so it is not a proxied page')
        m = page.evaluate(MEASURE)
        m['dropdown'] = page.evaluate(OPEN_FIRST)
        x, y, w, h = m['nav']
        page.screenshot(path=f'{out_dir}/nav-{name}.png', clip={'x': x, 'y': y, 'width': w, 'height': h + 260})
        results[name] = m
        print(f'{name}: {url}: nav {m["nav"]}, background {m["background"]}, padding {m["padding"]}, '
              f'{len(m["items"])} items, first dropdown {len(m["dropdown"])} entries')
    browser.close()

bad = diff('nav', results['native'], results['proxied'])
print('nav parity: identical' if not bad else f'nav parity: {bad} difference(s)')
sys.exit(1 if bad else 0)
