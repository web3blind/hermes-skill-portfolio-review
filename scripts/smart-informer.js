#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const skillDir = path.resolve(__dirname, '..');
const workspaceDir = path.resolve(skillDir, '..', '..');
const defaultAddressesPath = path.join(skillDir, 'addresses.conf');
const defaultStatePath = path.join(skillDir, 'informer-state.json');
const defaultSnapshotDirs = [
  path.join(workspaceDir, 'portfolio', 'snapshots'),
  path.join(workspaceDir, 'portfolio-history'),
];

function parseArgs(argv) {
  const args = {
    addresses: defaultAddressesPath,
    state: defaultStatePath,
    snapshotDirs: defaultSnapshotDirs.slice(),
    staleDays: 14,
    resendAfterDays: 21,
    dryRun: false,
    pretty: false,
    messageOnly: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = argv[i + 1];
    if (arg === '--addresses' && next) {
      args.addresses = path.resolve(next);
      i += 1;
    } else if (arg === '--state' && next) {
      args.state = path.resolve(next);
      i += 1;
    } else if (arg === '--no-default-snapshot-dirs') {
      args.snapshotDirs = [];
    } else if (arg === '--snapshot-dir' && next) {
      args.snapshotDirs.push(path.resolve(next));
      i += 1;
    } else if (arg === '--stale-days' && next) {
      args.staleDays = Number(next);
      i += 1;
    } else if (arg === '--resend-after-days' && next) {
      args.resendAfterDays = Number(next);
      i += 1;
    } else if (arg === '--dry-run') {
      args.dryRun = true;
    } else if (arg === '--pretty') {
      args.pretty = true;
    } else if (arg === '--message-only') {
      args.messageOnly = true;
    } else if (arg === '--help' || arg === '-h') {
      printHelp();
      process.exit(0);
    }
  }

  args.staleDays = Number.isFinite(args.staleDays) && args.staleDays > 0 ? args.staleDays : 14;
  args.resendAfterDays = Number.isFinite(args.resendAfterDays) && args.resendAfterDays > 0 ? args.resendAfterDays : 21;
  return args;
}

function printHelp() {
  console.log(`portfolio smart informer\n\nUsage:\n  node smart-informer.js [--dry-run] [--pretty] [--message-only] [--no-default-snapshot-dirs] [--snapshot-dir path]\n\nThe state intentionally stores no wallet addresses, balances, token amounts, or raw snapshot text.\nIt stores only hashes, timestamps, and decision metadata to suppress repeated reminders.\n`);
}

function sha256(value) {
  return crypto.createHash('sha256').update(String(value)).digest('hex');
}

function readJson(filePath, fallback) {
  try {
    const text = fs.readFileSync(filePath, 'utf8').trim();
    if (!text) return fallback;
    return JSON.parse(text);
  } catch (error) {
    if (error.code === 'ENOENT') return fallback;
    throw error;
  }
}

function writeJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

function normalizeState(raw) {
  const state = raw && typeof raw === 'object' ? { ...raw } : {};
  state.version = 1;
  state.lastRunAt = state.lastRunAt || null;
  state.lastSentAt = state.lastSentAt || null;
  state.lastSentFingerprint = state.lastSentFingerprint || null;
  state.addressSetHash = state.addressSetHash || null;
  state.latestSnapshotHash = state.latestSnapshotHash || null;
  state.lastDecision = state.lastDecision || null;
  return state;
}

function loadAddressSetHash(addressesPath) {
  let text = '';
  try {
    text = fs.readFileSync(addressesPath, 'utf8');
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }

  const entries = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#') && line.includes('='))
    .map((line) => {
      const [key, ...rest] = line.split('=');
      const type = key.trim().startsWith('sol_') ? 'sol' : key.trim().startsWith('evm_') ? 'evm' : 'unknown';
      return `${type}:${rest.join('=').trim().toLowerCase()}`;
    })
    .sort();

  return {
    count: entries.length,
    hash: sha256(entries.join('\n')).slice(0, 24),
  };
}

function listMarkdownFiles(dir) {
  try {
    return fs.readdirSync(dir, { withFileTypes: true })
      .filter((entry) => entry.isFile() && entry.name.toLowerCase().endsWith('.md'))
      .map((entry) => path.join(dir, entry.name));
  } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw error;
  }
}

function dateFromFilename(filePath) {
  const base = path.basename(filePath);
  const match = base.match(/(20\d{2})[-_](\d{2})(?:[-_](\d{2}))?/);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3] || 1);
  const date = new Date(Date.UTC(year, month - 1, day, 12, 0, 0));
  return Number.isNaN(date.getTime()) ? null : date;
}

function parseMoney(value) {
  if (!value) return null;
  const normalized = String(value).replace(/,/g, '').replace(/\s+/g, '');
  const num = Number(normalized);
  return Number.isFinite(num) ? num : null;
}

function formatUsd(value) {
  if (!Number.isFinite(value)) return null;
  return `$${Math.round(value).toLocaleString('en-US')}`;
}

function snapshotInsights(content) {
  const text = String(content || '');
  const totalMatch = text.match(/Rough total visible:\s*~?\$([0-9,]+(?:\.[0-9]+)?)/i);
  const total = totalMatch ? parseMoney(totalMatch[1]) : null;

  const walletValues = [];
  const evmSection = (text.split(/## EVM wallets/i)[1] || '').split(/## Solana wallet/i)[0] || '';
  for (const match of evmSection.matchAll(/^-\s+([^`\n:]+)`?[^\n]*?:\s*~?\$([0-9,]+(?:\.[0-9]+)?)/gm)) {
    const label = match[1].trim().replace(/\s+\/\s+.*$/, '').replace(/^evm_/, '');
    const value = parseMoney(match[2]);
    if (value !== null) walletValues.push({ label, value });
  }
  walletValues.sort((a, b) => b.value - a.value);
  const largest = walletValues[0] || null;

  let stableUsd = 0;
  const holdingsText = text.split(/## Notes \/ issues/i)[0] || text;
  for (const match of holdingsText.matchAll(/USDC[^\n]*?(?:~?\$([0-9,]+(?:\.[0-9]+)?)|:\s*([0-9,]+(?:\.[0-9]+)?))/gi)) {
    const value = parseMoney(match[1] || match[2]);
    if (value !== null) stableUsd += value;
  }

  const solanaTop = [];
  const solanaSection = text.split(/## Solana wallet/i)[1] || '';
  for (const match of solanaSection.matchAll(/^-\s+([A-Za-z0-9_.-]+):\s*~?\$([0-9,]+(?:\.[0-9]+)?)(?:,\s*24h\s*~?([+-]?[0-9.]+%))?/gm)) {
    solanaTop.push({ symbol: match[1], value: parseMoney(match[2]), change: match[3] || null });
    if (solanaTop.length >= 3) break;
  }

  const lines = [];
  if (total !== null) lines.push(`последний видимый total: около ${formatUsd(total)}`);
  if (stableUsd > 0 && total) {
    const pct = Math.round((stableUsd / total) * 100);
    lines.push(`видимые USDC/stables: около ${formatUsd(stableUsd)} (${pct}%)`);
  }
  if (largest && total) {
    const pct = Math.round((largest.value / total) * 100);
    lines.push(`крупнейший видимый кошелёк/карман: ${largest.label}, около ${pct}%`);
  }
  if (solanaTop.length) {
    const top = solanaTop.map((item) => `${item.symbol}${item.change ? ` ${item.change}` : ''}`).join(', ');
    lines.push(`Solana top: ${top}`);
  }

  const recommendations = [];
  if (stableUsd > 0 && total && stableUsd / total > 0.6) recommendations.push('проверить, не стала ли stable-доля слишком большой относительно целевой структуры');
  if (largest && total && largest.value / total > 0.6) recommendations.push('проверить концентрацию в крупнейшем кошельке/кармане');
  if (/DeBank[^\n]*not verified|DeFi\/NFT\/LP positions were not verified/i.test(text)) recommendations.push('перепроверить DeFi/NFT/LP позиции через полноценный /portfolio, потому что snapshot мог их не видеть');
  if (!recommendations.length) recommendations.push('сверить доли, stable buffer, новые/закрытые позиции и крупные просадки');

  return { lines, recommendations };
}

function findLatestSnapshot(snapshotDirs) {
  const files = snapshotDirs.flatMap(listMarkdownFiles);
  const snapshots = files.map((filePath) => {
    const stat = fs.statSync(filePath);
    const namedDate = dateFromFilename(filePath);
    const date = namedDate || stat.mtime;
    const content = fs.readFileSync(filePath, 'utf8');
    return {
      filePath,
      date,
      mtime: stat.mtime,
      hash: sha256(`${path.basename(filePath)}\n${content}`).slice(0, 24),
      insights: snapshotInsights(content),
    };
  });

  snapshots.sort((a, b) => b.date.getTime() - a.date.getTime());
  return snapshots[0] || null;
}

function daysBetween(a, b) {
  return Math.floor((a.getTime() - b.getTime()) / 86400000);
}

function monthKey(date) {
  return date.toISOString().slice(0, 7);
}


function buildSnapshotReminder(latestSnapshot, ageDays) {
  const lines = [`Портфолио: последний snapshot старше ${ageDays} дн. Стоит запустить /portfolio.`];
  const insights = latestSnapshot && latestSnapshot.insights ? latestSnapshot.insights : null;
  if (insights && insights.lines && insights.lines.length) {
    lines.push('', 'Что было в последнем snapshot:');
    for (const line of insights.lines.slice(0, 4)) lines.push(`- ${line}`);
  }
  if (insights && insights.recommendations && insights.recommendations.length) {
    lines.push('', 'Что проверить:');
    for (const line of insights.recommendations.slice(0, 4)) lines.push(`- ${line}`);
  } else {
    lines.push('', 'Что проверить:', '- доли портфеля, stable buffer, концентрацию, новые/закрытые позиции и крупные просадки');
  }
  return lines.join('\n');
}

function shouldResend(state, now, fingerprint, resendAfterDays) {
  if (state.lastSentFingerprint !== fingerprint) return true;
  if (!state.lastSentAt) return true;
  const last = new Date(state.lastSentAt);
  if (Number.isNaN(last.getTime())) return true;
  return daysBetween(now, last) >= resendAfterDays;
}

function decide({ state, now, addressSet, latestSnapshot, staleDays, resendAfterDays }) {
  const hasPreviousRun = Boolean(state.lastRunAt);

  if (hasPreviousRun && state.addressSetHash && state.addressSetHash !== addressSet.hash) {
    const fingerprint = `address-set-changed:${addressSet.hash}`;
    if (shouldResend(state, now, fingerprint, resendAfterDays)) {
      return {
        send: true,
        reason: 'address_set_changed',
        fingerprint,
        message: 'Портфолио: список кошельков изменился. Стоит запустить /portfolio и обновить snapshot, чтобы следующие проверки сравнивали уже актуальную структуру.',
      };
    }
  }

  if (!latestSnapshot) {
    const fingerprint = `no-snapshot:${monthKey(now)}`;
    if (shouldResend(state, now, fingerprint, resendAfterDays)) {
      return {
        send: true,
        reason: 'no_snapshot_this_month',
        fingerprint,
        message: 'Портфолио: нет сохранённого snapshot за текущий период. Стоит запустить /portfolio, проверить кошельки и сохранить снимок для сравнения без повторных напоминаний.',
      };
    }
    return { send: false, reason: 'no_snapshot_already_reminded', fingerprint };
  }

  const ageDays = Math.max(0, daysBetween(now, latestSnapshot.date));
  if (ageDays >= staleDays) {
    const bucket = Math.floor(ageDays / resendAfterDays);
    const fingerprint = `snapshot-stale:${latestSnapshot.hash}:bucket-${bucket}`;
    if (shouldResend(state, now, fingerprint, resendAfterDays)) {
      return {
        send: true,
        reason: 'snapshot_stale',
        fingerprint,
        message: buildSnapshotReminder(latestSnapshot, ageDays),
      };
    }
    return { send: false, reason: 'snapshot_stale_already_reminded', fingerprint, ageDays };
  }

  return {
    send: false,
    reason: 'snapshot_fresh',
    fingerprint: `snapshot-fresh:${latestSnapshot.hash}`,
    ageDays,
  };
}

function run(args) {
  const now = new Date();
  const state = normalizeState(readJson(args.state, {}));
  const addressSet = loadAddressSetHash(args.addresses);
  const latestSnapshot = findLatestSnapshot(args.snapshotDirs);
  const decision = decide({
    state,
    now,
    addressSet,
    latestSnapshot,
    staleDays: args.staleDays,
    resendAfterDays: args.resendAfterDays,
  });

  const nextState = {
    version: 1,
    lastRunAt: now.toISOString(),
    lastSentAt: decision.send ? now.toISOString() : state.lastSentAt,
    lastSentFingerprint: decision.send ? decision.fingerprint : state.lastSentFingerprint,
    addressSetHash: addressSet.hash,
    latestSnapshotHash: latestSnapshot ? latestSnapshot.hash : null,
    lastDecision: {
      at: now.toISOString(),
      reason: decision.reason,
      sent: Boolean(decision.send),
      addressCount: addressSet.count,
      latestSnapshotAgeDays: latestSnapshot ? Math.max(0, daysBetween(now, latestSnapshot.date)) : null,
    },
  };

  if (!args.dryRun) writeJson(args.state, nextState);

  return {
    ok: true,
    dryRun: args.dryRun,
    checkedAt: now.toISOString(),
    send: Boolean(decision.send),
    message: decision.send ? decision.message : '',
    reason: decision.reason,
    privacy: 'state stores hashes/timestamps/decision metadata only; no wallet addresses, balances, token amounts, or raw snapshot text',
    statePath: args.state,
    addressCount: addressSet.count,
    latestSnapshotAgeDays: latestSnapshot ? Math.max(0, daysBetween(now, latestSnapshot.date)) : null,
  };
}

if (require.main === module) {
  const args = parseArgs(process.argv.slice(2));
  try {
    const result = run(args);
    if (args.messageOnly) {
      process.stdout.write(`${result.message || 'NO_REPLY'}\n`);
    } else {
      process.stdout.write(`${JSON.stringify(result, null, args.pretty ? 2 : 0)}\n`);
    }
  } catch (error) {
    process.stderr.write(`${JSON.stringify({ ok: false, error: error.message || String(error) }, null, 2)}\n`);
    process.exit(1);
  }
}

module.exports = { decide, run };
