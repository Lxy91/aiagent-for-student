import { build } from 'esbuild';
import { zipSync } from 'fflate';
import { cp, mkdir, readFile, readdir, writeFile, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.dirname(fileURLToPath(import.meta.url));
const dist = path.join(root, 'dist');
if (path.dirname(path.resolve(dist)) !== path.resolve(root) || path.basename(dist) !== 'dist')
  throw new Error('Invalid build output directory');
await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
await build({
  absWorkingDir: root,
  entryPoints: { popup: 'popup.js', 'resume-profile': 'resume-profile.js' },
  outdir: dist,
  bundle: true,
  platform: 'browser',
  format: 'esm',
  target: 'chrome120',
  splitting: true,
  minify: true,
  legalComments: 'eof',
});
await build({
  absWorkingDir: root,
  entryPoints: { 'model-provider': 'model-provider.mjs', 'model-planner': 'model-planner.mjs' },
  outdir: dist,
  splitting: true,
  outExtension: { '.js': '.mjs' },
  chunkNames: 'server-[name]-[hash]',
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: 'node22',
  external: ['exceljs', 'pdfjs-dist/*', 'mammoth/*'],
});
for (const name of [
  'manifest.json',
  'popup.html',
  'popup.css',
  'form-filler.js',
  'README.md',
  'service.mjs',
  '.env.example',
  'start-model-service.cmd',
]) {
  await cp(path.join(root, name), path.join(dist, name));
}
const pdfRoot = path.dirname(fileURLToPath(import.meta.resolve('pdfjs-dist/package.json')));
await cp(path.join(pdfRoot, 'build/pdf.worker.min.mjs'), path.join(dist, 'pdf.worker.min.mjs'));
await cp(path.join(pdfRoot, 'cmaps'), path.join(dist, 'cmaps'), { recursive: true });
await cp(path.join(pdfRoot, 'standard_fonts'), path.join(dist, 'standard_fonts'), {
  recursive: true,
});
await cp(path.join(pdfRoot, 'LICENSE'), path.join(dist, 'PDFJS-LICENSE'));
const mammothRoot = path.dirname(fileURLToPath(import.meta.resolve('mammoth/package.json')));
await cp(path.join(mammothRoot, 'LICENSE'), path.join(dist, 'MAMMOTH-LICENSE'));
const excelRoot = path.dirname(fileURLToPath(import.meta.resolve('exceljs/package.json')));
await cp(path.join(excelRoot, 'LICENSE'), path.join(dist, 'EXCELJS-LICENSE'));
const manifest = JSON.parse(await readFile(path.join(root, 'manifest.json'), 'utf8'));
await writeFile(
  path.join(dist, 'package.json'),
  JSON.stringify(
    {
      name: 'qicheng-application-assistant-local-service',
      version: manifest.version,
      private: true,
      type: 'module',
      engines: { node: '>=22' },
      scripts: { start: 'node service.mjs' },
    },
    null,
    2,
  ) + '\n',
);
const entries = {};
async function collect(directory, prefix = '') {
  for (const item of await readdir(directory, { withFileTypes: true })) {
    const relative = `${prefix}${item.name}`;
    if (item.isDirectory()) await collect(path.join(directory, item.name), `${relative}/`);
    else entries[relative] = new Uint8Array(await readFile(path.join(directory, item.name)));
  }
}
await collect(dist);
const zip = zipSync(entries, { level: 6 });
const output = path.resolve(root, '../web/public/plugins');
await mkdir(output, { recursive: true });
await writeFile(path.join(output, 'application-assistant.zip'), zip);
console.log(`独立插件已打包：${dist}；应用市场安装包 ${zip.length} bytes`);
