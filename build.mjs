// Build Strike 27: joins the source files in src/ into the two playable pages.
//   node build.mjs
// Output: game/strike27.html (page fragment for hosting inside a wrapper) and index.html (standalone).
import { readFileSync, writeFileSync, readdirSync, mkdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = dirname(fileURLToPath(import.meta.url));
const read = f => readFileSync(join(root, f), 'utf8');
const THREE_URL = 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.min.js';

// Source files share one module scope and are joined in filename order (00-… first, 99-main last).
const files = readdirSync(join(root, 'src/js')).filter(f => f.endsWith('.js')).sort();
const js = `import * as THREE from '${THREE_URL}';\n` + files.map(f => read('src/js/' + f)).join('\n');

// Catch syntax errors before anything is written.
mkdirSync(join(root, '.build'), { recursive: true });
writeFileSync(join(root, '.build/bundle.mjs'), js);
execFileSync(process.execPath, ['--check', join(root, '.build/bundle.mjs')], { stdio: 'inherit' });

const page = read('src/head.html') + '<style>\n' + read('src/style.css') + '</style>\n' + read('src/shell.html')
  + '<script type="module">\n' + js + '</script>\n';

writeFileSync(join(root, 'game/strike27.html'), page);
writeFileSync(join(root, 'index.html'),
  '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
  + '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">\n</head>\n<body>\n'
  + page + '\n</body>\n</html>\n');

console.log(`built ${files.length} source files → game/strike27.html (${(page.length / 1024).toFixed(0)} KB), index.html`);
