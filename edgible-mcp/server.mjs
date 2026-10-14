#!/usr/bin/env node
// Edgible MCP server, over stdio: read-only tools over Edgible's cards, and over the apps the
// local Edgible CLI's sign-in can see. It has no HTTP or auth code of its own: run it from an
// MCP client, or publish it with the mcp-bridge app card, whose hostname uses
// Edgible's api-key auth. stdout is the protocol, so every log goes to stderr.

import { execFile, spawn } from 'node:child_process';
import { mkdir, mkdtemp, readdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { homedir, tmpdir } from 'node:os';
import path from 'node:path';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import YAML from 'yaml';
import { z } from 'zod';

const CATALOG_TTL = Number(process.env.EDGIBLE_MCP_CATALOG_TTL || 900) * 1000;
const CACHE_DIR = process.env.EDGIBLE_MCP_CACHE_DIR || path.join(process.env.XDG_CACHE_HOME || path.join(homedir(), '.cache'), 'edgible-mcp');
const RUNNING_TTL = 30 * 1000;
const REPO = 'edgible-org/cards';
const KIT = 'edgible-org/card-kit';
const STATUS_URL = `https://raw.githubusercontent.com/${REPO}/test-status/status.json`;
// How to sign the CLI in, where this server runs. The edgible-mcp card sets its own.
const SIGN_IN = process.env.EDGIBLE_MCP_SIGN_IN || 'edgible auth login';

// ---------- The catalog: cards and the needs map, from GitHub main ----------

async function fetchRepo(repo) {
  const dir = await mkdtemp(path.join(tmpdir(), 'catalog-'));
  const res = await fetch(`https://codeload.github.com/${repo}/tar.gz/refs/heads/main`);
  if (!res.ok) throw new Error(`fetching ${repo}: HTTP ${res.status}`);
  const tar = spawn('tar', ['-xz', '--strip-components=1', '-C', dir]);
  const done = new Promise((ok, fail) => tar.on('close', (code) => (code ? fail(new Error(`tar exited ${code}`)) : ok())));
  for await (const chunk of res.body) tar.stdin.write(chunk);
  tar.stdin.end();
  await done;
  return dir;
}

const readText = (file) => readFile(file, 'utf8').catch(() => null);

// The README's level-2 sections, by heading.
function sections(markdown) {
  const out = {};
  let name = null;
  for (const line of (markdown || '').split('\n')) {
    const m = line.match(/^## (.+)/);
    if (m) { name = m[1].trim(); out[name] = []; } else if (name) out[name].push(line);
  }
  return Object.fromEntries(Object.entries(out).map(([k, v]) => [k, v.join('\n').trim()]));
}

async function loadItems(dir) {
  const items = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue;
    const card = await readText(path.join(dir, entry.name, 'card.yml'));
    if (!card) continue;
    const yml = YAML.parse(card);
    const readme = await readText(path.join(dir, entry.name, 'README.md'));
    const test = await readText(path.join(dir, entry.name, 'test.yml'));
    items.push({
      // app: one tested app; pattern: several apps wired together.
      type: yml?.metadata?.type || 'app', name: entry.name,
      url: `https://github.com/${REPO}/tree/main/${entry.name}`,
      description: yml?.metadata?.description || '',
      applications: yml?.applications || [],
      places: yml?.places || {},
      sections: sections(readme),
      test: test ? YAML.parse(test) : null,
    });
  }
  return items;
}

async function loadStatus() {
  try {
    const res = await fetch(STATUS_URL);
    return res.ok ? await res.json() : {};
  } catch { return {}; }
}

let catalog = null;
let catalogLoading = null;
const CACHE_FILE = path.join(CACHE_DIR, 'catalog.json');

async function readCache() {
  // A cache in an older shape has no repo: fetch afresh.
  try { const c = JSON.parse(await readFile(CACHE_FILE, 'utf8')); return c.repo === REPO ? c : null; } catch { return null; }
}

async function writeCache(c) {
  try {
    await mkdir(CACHE_DIR, { recursive: true });
    const tmp = `${CACHE_FILE}.${process.pid}`;
    await writeFile(tmp, JSON.stringify(c));
    await rename(tmp, CACHE_FILE);
  } catch (err) { console.error(`catalog cache: ${err.message}`); }
}

async function getCatalog() {
  if (catalog && Date.now() - catalog.at < CATALOG_TTL) return catalog;
  if (!catalog) catalog = await readCache();
  if (catalog && Date.now() - catalog.at < CATALOG_TTL) return catalog;
  catalogLoading ??= (async () => {
    const dirs = [];
    try {
      const [cards, kit] = await Promise.all([fetchRepo(REPO), fetchRepo(KIT)]);
      dirs.push(cards, kit);
      const needs = YAML.parse(await readFile(path.join(kit, 'skills/edgible-cards/needs-map.yaml'), 'utf8')) || [];
      const items = await loadItems(cards);
      const status = await loadStatus();
      catalog = { at: Date.now(), repo: REPO, needs, items, status };
      await writeCache(catalog);
      return catalog;
    } finally {
      catalogLoading = null;
      for (const d of dirs) rm(d, { recursive: true, force: true });
    }
  })();
  try {
    return await catalogLoading;
  } catch (err) {
    if (catalog) return catalog; // keep serving the last good copy when GitHub is unreachable
    throw err;
  }
}

// ---------- Search ----------

const STOP = new Set('a an and are as at be but by can for from get have how i in into is it its me my of on or our so some something that the their them this to up use want we what when where which with without would you your need needs app apps self host hosted hosting run running server service tool thing team let away somewhere own place'.split(' '));

function words(text) {
  return String(text || '').toLowerCase().match(/[a-z0-9+.#-]+/g)?.map((w) => w.replace(/[.-]+$/, '').replace(/(?<=..)(ies)$/, 'y').replace(/(?<=...)s$/, ''))
    .filter((w) => w && !STOP.has(w)) || [];
}

function score(query, fields) {
  const q = new Set(words(query));
  let total = 0;
  for (const [text, weight] of fields) {
    const have = new Set(words(text));
    for (const w of q) if (have.has(w)) total += weight;
  }
  // A whole phrase from the query, such as a product name, counts extra.
  const lower = query.toLowerCase();
  for (const [text, weight] of fields) {
    for (const phrase of [].concat(text || [])) {
      const p = String(phrase).toLowerCase();
      if (p.length > 3 && lower.includes(p)) total += weight * 2;
    }
  }
  return total;
}

function itemFields(item) {
  return [
    [item.name, 4], [item.description, 3],
    [item.applications.map((a) => `${a.name} ${a.what} ${a.from}`).join(' '), 2],
    [item.sections.Why, 1], [item.sections.What, 1],
  ];
}

function statusOf(cat, item) {
  const s = cat.status[item.name];
  if (s && typeof s === 'object') return `${s.result} on Edgible ${s['edgible-cli']}, ${s.tested} (nightly test)`;
  if (item.test) return `test.yml: ${item.test.result}, ${item.test.tested}`;
  return 'not tested';
}

function authLine(item) {
  return item.applications.map((a) => `${a.name} (${a.protocol}, ${(a.authModes || []).join('+')})`).join(', ');
}

async function find({ need }) {
  const cat = await getCatalog();
  const needs = cat.needs
    .map((n) => ({ n, s: score(need, [[n.category, 2], [n.jobs, 3], [n.replaces, 4]]) }))
    .filter((x) => x.s > 0).sort((a, b) => b.s - a.s).filter((x, _, all) => x.s >= all[0].s * 0.5).slice(0, 3).map((x) => x.n);
  const named = new Set(needs.flatMap((n) => n.cards || []));
  const items = cat.items
    .map((item) => ({ item, s: score(need, itemFields(item)) + (named.has(item.name) ? 5 : 0) }))
    .filter((x) => x.s > 0).sort((a, b) => b.s - a.s).filter((x, _, all) => x.s >= all[0].s * 0.4).slice(0, 6).map((x) => x.item);

  const out = [`# Cards for: ${need}`, ''];
  if (!needs.length && !items.length) {
    out.push('No need in the map and no card matched these words. Try other words, such as the app or the hosted service it replaces.',
      `Every card: ${cat.items.map((i) => `${i.name} (${i.type})`).join(', ')}.`,
      'When none fits, an app can be chosen from awesome-selfhosted and built into an app card: see https://github.com/edgible-org/card-kit#agent-skill.');
    return out.join('\n');
  }
  if (items.length) {
    out.push('## Cards', '');
    for (const i of items) {
      out.push(`- **${i.name}** (${i.type}): ${i.description}`,
        `  - apps: ${authLine(i)}`,
        `  - status: ${statusOf(cat, i)}`,
        `  - ${i.url}`);
    }
    out.push('');
  }
  for (const n of needs) {
    out.push(`## Need: ${n.category}`, '',
      `- fit: ${n.fit?.rating}${n.fit?.why ? `, ${n.fit.why}` : ''}`,
      `- exposure: ${n.exposure?.default}`);
    if (n.exposure?.sensitive) out.push(`- when the data is sensitive: ${n.exposure.sensitive}`);
    if (n.exposure?.regulated) out.push(`- when the data is regulated: ${n.exposure.regulated}`);
    if (n.machine) out.push(`- machine: ${n.machine}`);
    if (n.permissions) out.push(`- permissions: ${n.permissions}`);
    const have = (n.cards || []).map((c) => `${c} (${cat.items.find((i) => i.name === c)?.type || 'card'})`);
    out.push(`- cards: ${have.length ? have.join(', ') : 'none yet; an app can be chosen and built into an app card'}`);
    if (n.ask?.length) out.push(`- ask: ${n.ask.join(' / ')}`);
    if (n.find) out.push(`- where to find apps: ${n.find}`);
    out.push('');
  }
  out.push('Use describe for the full story of one card.');
  return out.join('\n');
}

async function describe({ name }) {
  const cat = await getCatalog();
  const matches = cat.items.filter((i) => i.name === name.toLowerCase().trim());
  if (!matches.length) {
    const near = cat.items.filter((i) => i.name.includes(name.toLowerCase()) || name.toLowerCase().includes(i.name)).map((i) => i.name);
    return `No card is called "${name}".${near.length ? ` Did you mean: ${near.join(', ')}?` : ''} Use find to search by need.`;
  }
  return matches.map((i) => {
    const out = [`# ${i.name} (${i.type})`, '', i.description, '', i.url, ''];
    out.push('## Apps', '', '| App | What | Image | Port | Protocol | Auth | Place |', '| --- | --- | --- | --- | --- | --- | --- |');
    for (const a of i.applications) out.push(`| ${a.name} | ${a.what} | ${a.from} | ${a.port} | ${a.protocol} | ${(a.authModes || []).join(', ')} | ${a.place} |`);
    out.push('');
    const places = Object.entries(i.places);
    if (places.length) {
      out.push('## Minimum machine', '');
      for (const [p, v] of places) out.push(`- ${p}: ${['memory', 'disk', 'gpu'].filter((k) => v[k]).map((k) => `${k} ${v[k]}`).join(', ')}${v.arch ? `, ${v.arch.join('/')}` : ''}${v.runs ? `, runs ${v.runs.join(', ')}` : ''}`);
      out.push('');
    }
    out.push('## Tested', '', `- status: ${statusOf(cat, i)}`);
    if (i.test) {
      out.push(`- last test.yml: ${i.test.result} on ${i.test.tested}, Edgible CLI ${i.test['edgible-cli']}, ${i.test.machine}`);
      if (i.test.images?.length) out.push(`- images: ${i.test.images.map((x) => x.split('@')[0]).join(', ')}`);
    }
    out.push('');
    for (const h of ['Why', 'What']) if (i.sections[h]) out.push(`## ${h}`, '', i.sections[h], '');
    const needs = cat.needs.filter((n) => (n.cards || []).includes(i.name)).map((n) => n.category);
    if (needs.length) out.push(`Needs it answers: ${needs.join(', ')}.`, '');
    out.push(`How to run it: the README's How, Verify, and Tear down sections, at ${i.url}#how.`);
    return out.join('\n');
  }).join('\n\n---\n\n');
}

// ---------- What is running, and whether it works ----------

function edgible(args, timeout = 60000) {
  return new Promise((resolve) => {
    execFile('edgible', args, { timeout, maxBuffer: 16 << 20, env: { ...process.env, NO_COLOR: '1', EDGIBLE_NO_UPDATE_NOTIFIER: '1', EDGIBLE_NO_INTERACTIVE: '1' } },
      (err, stdout, stderr) => {
        let json = null;
        try { json = JSON.parse(stdout); } catch { /* not JSON */ }
        resolve({ ok: !err, code: err?.code ?? 0, json, stdout, stderr });
      });
  });
}

async function mapLimit(list, limit, fn) {
  const out = new Array(list.length);
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(limit, list.length) }, async () => {
    while (next < list.length) { const i = next++; out[i] = await fn(list[i]); }
  }));
  return out;
}

function authModesOf(detail) {
  const modes = new Set();
  for (const a of detail?.access || []) for (const r of a.routes || []) for (const m of r.auth || []) modes.add(m === 'edgible-login' ? 'org' : m);
  return [...modes];
}

// How a hostname should answer a request with no credentials, by its auth modes.
function expected(modes) {
  if (modes.includes('none')) return { text: 'the app answers', ok: (s) => s > 0 && s < 500 };
  if (modes.includes('org') && modes.includes('api-key')) return { text: 'a redirect to sign in, or 401', ok: (s, loc) => s === 401 || (s >= 300 && s < 400 && !!loc) };
  if (modes.includes('org')) return { text: 'a redirect to the Edgible sign-in', ok: (s, loc) => s >= 300 && s < 400 && !!loc };
  if (modes.includes('api-key')) return { text: '401 until a key is sent', ok: (s) => s === 401 };
  return { text: 'an answer', ok: (s) => s > 0 && s < 500 };
}

async function probe(host, modes) {
  const want = expected(modes);
  try {
    const res = await fetch(`https://${host}/`, { redirect: 'manual', signal: AbortSignal.timeout(10000) });
    const loc = res.headers.get('location');
    await res.body?.cancel();
    const ok = want.ok(res.status, loc);
    return { host, ok, evidence: `${res.status}${loc ? ` -> ${loc.replace(/\?.*/, '')}` : ''}`, want: want.text };
  } catch (err) {
    return { host, ok: false, evidence: err.cause?.code || err.name || String(err), want: want.text };
  }
}

const isSystemApp = (a) => /-ingest$/.test(a.name) && /^device-/.test(a.name);
let running = null;

async function whoami() {
  const who = await edgible(['whoami']);
  if (!who.json?.loggedIn) return null;
  return who.json;
}

async function whatsRunning({ app, device }) {
  const who = await whoami();
  if (!who) {
    return ['The Edgible CLI this server runs is not signed in, so it cannot see your apps.',
      'To sign it in, run this on the machine that runs the server, and open the link it prints:',
      '', `    ${SIGN_IN}`, '',
      'find and describe work without it.'].join('\n');
  }
  if (app && !/^[A-Za-z0-9_-]{1,64}$/.test(app)) return `"${app}" is not an app name.`;

  if (!running || Date.now() - running.at > RUNNING_TTL) {
    const [apps, devices] = await Promise.all([edgible(['app', 'list']), edgible(['device', 'list'])]);
    if (!apps.json) return `edgible app list failed: ${(apps.stderr || apps.stdout).trim().slice(0, 500)}`;
    running = { at: Date.now(), apps: apps.json, devices: devices.json || [] };
  }
  let apps = running.apps;
  if (app) apps = apps.filter((a) => a.name === app || a.id === app);
  if (device) apps = apps.filter((a) => (a.devices || []).some((d) => d.name === device || d.id === device));
  if (app && !apps.length) return `No app called "${app}" in ${who.organization?.name}. Apps: ${running.apps.filter((a) => !isSystemApp(a)).map((a) => a.name).join(', ')}.`;
  const system = apps.filter(isSystemApp);
  apps = apps.filter((a) => !isSystemApp(a) || app);

  const rows = await mapLimit(apps, 8, async (a) => {
    const detail = (await edgible(['app', 'get', a.id])).json;
    const modes = authModesOf(detail);
    const probes = a.protocol === 'https' ? await Promise.all((a.hostnames || []).map((h) => probe(h, modes))) : [];
    const certs = (detail?.certificates || []).filter((c) => c.status !== 'issued').map((c) => `${c.hostname}: ${c.status}`);
    const issues = (detail?.deploymentIssues || []).map((i) => i.message || JSON.stringify(i));
    return { a, modes, probes, certs, issues };
  });

  const out = [`# Apps in ${who.organization?.name} (signed in as ${who.account})`, ''];
  const devs = running.devices.filter((d) => !device || d.name === device || d.id === device);
  out.push('## Devices', '', devs.map((d) => `- ${d.name}: ${d.status}${d.agentVersion ? `, agent ${d.agentVersion}` : ''}`).join('\n') || '- none', '');
  out.push('## Apps', '', '| App | Device | Port | Auth | Status | Works | Evidence |', '| --- | --- | --- | --- | --- | --- | --- |');
  for (const { a, modes, probes, certs, issues } of rows) {
    const devName = (a.devices || []).map((d) => d.name).join(', ');
    const offline = (a.devices || []).some((d) => running.devices.find((x) => x.id === d.id)?.status === 'offline');
    let works;
    if (a.protocol !== 'https') works = 'not checked';
    else if (probes.length && probes.every((p) => p.ok) && !certs.length && !issues.length) works = 'yes';
    else works = 'no';
    const evidence = [
      ...probes.map((p) => `${p.host}: ${p.evidence} (expected ${p.want})`),
      ...certs.map((c) => `certificate ${c}`), ...issues,
      ...(offline ? ['its device is offline'] : []),
      ...(a.protocol !== 'https' ? [`${a.protocol}, ${(a.hostnames || []).join(', ')}`] : []),
    ].join('; ');
    out.push(`| ${a.name} | ${devName} | ${a.port} | ${a.protocol !== 'https' ? `none (${a.protocol})` : modes.join(', ') || '?'} | ${a.status} | ${works} | ${evidence} |`);
  }
  if (system.length && !app) out.push('', `Also ${system.length} Edgible device-ingest apps, which Edgible runs for each device. They are not listed.`);

  if (app && rows.length === 1) {
    const doc = await edgible(['app', 'doctor', rows[0].a.id, '--json'], 90000);
    const d = doc.json;
    if (d) {
      out.push('', `## edgible app doctor ${rows[0].a.name}`, '', `- verdict: ${d.verdict?.status}${d.verdict?.layer ? ` at ${d.verdict.layer}` : ''}: ${d.verdict?.message || ''}`);
      for (const f of d.findings || []) {
        const note = /logs are not collectable for this workload type/.test(f.message || '') ? ' (expected for an existing app: Edgible does not collect its logs)' : '';
        out.push(`- ${f.severity} at ${f.layer}: ${f.message}${note}`);
      }
      const hops = d.checks?.trace?.hops;
      if (Array.isArray(hops)) out.push(`- data path: ${hops.map((h) => `${h.hop}: ${h.verdict}${h.reason ? ` (${h.reason})` : ''}`).join(' -> ')}`);
    } else {
      out.push('', `edgible app doctor failed: ${(doc.stderr || doc.stdout).trim().slice(0, 500)}`);
    }
  }
  out.push('', 'Works means each hostname answered, with no credentials, the way its auth mode says. It does not prove the app does its job: check that end to end, such as signing in.');
  return out.join('\n');
}

// ---------- MCP ----------

function buildServer() {
  const server = new McpServer({ name: 'edgible', version: '0.4.0' }, {
    instructions: 'Read-only tools for Edgible. find searches Edgible cards, each an app card (one tested self-hosted app) or a pattern card (several apps wired together), for a need, with how well it suits Edgible and how to publish it. describe shows one in full. whats_running lists the apps and devices of the Edgible organization this server is signed in to, and checks that each hostname answers the way its auth mode says. None of them changes anything.',
  });
  const text = (fn) => async (args) => {
    try { return { content: [{ type: 'text', text: await fn(args) }] }; } catch (err) {
      return { isError: true, content: [{ type: 'text', text: `Failed: ${err.message}` }] };
    }
  };
  const ro = { readOnlyHint: true, destructiveHint: false, idempotentHint: true };
  server.registerTool('find', {
    title: 'Find cards for a need',
    description: 'Search Edgible cards (type app: one app; type pattern: several apps wired together) for a need described in plain words ("somewhere for my bookmarks", "Pocket shut down", "a Git server for my team"), or an app name. Returns matching cards with their type, and the needs-map entries: how well it suits Edgible, the auth mode to publish with, what the machine needs, and the questions that change the answer.',
    inputSchema: { need: z.string().min(2).max(300).describe('The need or app, in the person\'s words') },
    annotations: { ...ro, openWorldHint: true },
  }, text(find));
  server.registerTool('describe', {
    title: 'Describe a card',
    description: 'Show one Edgible card: its type (app or pattern), its apps, images, ports, auth mode per hostname, minimum machine, test status, and the Why and What from its README, with a link to its How.',
    inputSchema: {
      name: z.string().min(1).max(64).describe('The card name, such as linkding or ci'),
    },
    annotations: { ...ro, openWorldHint: true },
  }, text(describe));
  server.registerTool('whats_running', {
    title: 'What is running, and does it work',
    description: 'List the devices and published apps of the Edgible organization this server is signed in to, and check each https hostname answers the way its auth mode says (none: the app; org: a redirect to sign in; api-key: 401). Give an app name for that app alone, with edgible app doctor\'s verdict. Takes up to a minute for many apps.',
    inputSchema: {
      app: z.string().max(64).optional().describe('One app name or id'),
      device: z.string().max(128).optional().describe('Only apps on this device name or id'),
    },
    annotations: { ...ro, openWorldHint: true },
  }, text(whatsRunning));
  return server;
}

const server = buildServer();
await server.connect(new StdioServerTransport());
console.error('edgible-mcp: serving over stdio');
