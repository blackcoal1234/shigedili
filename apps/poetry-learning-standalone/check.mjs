import fs from 'node:fs';

const html = fs.readFileSync('index.html', 'utf8');
const requiredNav = ['首页', '学习路径', '诗篇精读', '练习', '今日复习'];
const failures = [];

for (const label of requiredNav) {
  if (!html.includes(`data-page=\"${({首页:'home',学习路径:'path',诗篇精读:'read',练习:'practice',今日复习:'review'})[label]}\"`)) failures.push(`missing nav: ${label}`);
}
for (const value of ['default', 'ink', 'vermilion']) {
  if (!html.includes(`value=\"${value}\"`)) failures.push(`missing variant: ${value}`);
}
if (/\b(?:src|href)=["']https?:\/\//i.test(html)) failures.push('external hotlink found');
if (!html.includes('aria-current') || !html.includes('aria-pressed')) failures.push('navigation/card ARIA missing');
if (!html.includes('aria-expanded=\"false\"') || !html.includes('aria-controls=\"tw\"')) failures.push('Tweaks ARIA missing');
if (!html.includes("event.key==='Enter'||event.key===' '")) failures.push('card keyboard activation missing');
if (html.includes('scrollIntoView')) failures.push('scrollIntoView is forbidden');
const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
try { new Function(script ?? ''); } catch (error) { failures.push(`inline script syntax: ${error.message}`); }

if (failures.length) {
  console.error(failures.join('\n'));
  process.exit(1);
}
console.log('static check passed: nav, variants, local assets, ARIA, scroll behavior');
