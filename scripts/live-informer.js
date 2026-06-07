#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const skillDir = path.resolve(__dirname, '..');
const addressesPath = path.join(skillDir, 'addresses.conf');
const statePathDefault = path.join(skillDir, 'live-informer-state.json');

const EVM_CHAINS = [
  { id: 'eth', name: 'Ethereum', debank: 'eth', rpc: 'https://ethereum.publicnode.com', native: 'ETH', nativePriceId: 'ethereum', usdc: '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48', usdcDecimals: 6 },
  { id: 'base', name: 'Base', debank: 'base', rpc: 'https://mainnet.base.org', native: 'ETH', nativePriceId: 'ethereum', usdc: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', usdcDecimals: 6 },
  { id: 'arb', name: 'Arbitrum', debank: 'arb', rpc: 'https://arb1.arbitrum.io/rpc', native: 'ETH', nativePriceId: 'ethereum', usdc: '0xaf88d065e77c8cC2239327C5EDb3A432268e5831', usdcDecimals: 6 },
  { id: 'op', name: 'Optimism', debank: 'op', rpc: 'https://mainnet.optimism.io', native: 'ETH', nativePriceId: 'ethereum', usdc: '0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85', usdcDecimals: 6 },
  { id: 'bsc', name: 'BNB Chain', debank: 'bsc', rpc: 'https://bsc-dataseed.binance.org', native: 'BNB', nativePriceId: 'binancecoin' },
  { id: 'polygon', name: 'Polygon', debank: 'matic' },
  { id: 'avax', name: 'Avalanche', debank: 'avax' },
  { id: 'linea', name: 'Linea', debank: 'linea' },
  { id: 'scroll', name: 'Scroll', debank: 'scrl' },
  { id: 'zksync', name: 'zkSync Era', debank: 'era' },
];

const STABLE_SYMBOLS = new Set(['USDC', 'USDT', 'DAI', 'USDE', 'SUSDE', 'USDS', 'FRAX', 'LUSD', 'PYUSD']);

const SOL_RPC = 'https://api.mainnet-beta.solana.com';
const USDC_SOL_MINT = ['EPjFWdd5AufqSSqe', 'M2qN1xzybapC8G4wEGGkZwyTDt1v'].join('');
const SOL_MINT = 'So11111111111111111111111111111111111111112';

function parseArgs(argv) {
  const args = { state: statePathDefault, dryRun: false, pretty: false, messageOnly: false, thresholdPct: 5, thresholdUsd: 25 };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = argv[i + 1];
    if (arg === '--state' && next) { args.state = path.resolve(next); i += 1; }
    else if (arg === '--threshold-pct' && next) { args.thresholdPct = Number(next); i += 1; }
    else if (arg === '--threshold-usd' && next) { args.thresholdUsd = Number(next); i += 1; }
    else if (arg === '--dry-run') args.dryRun = true;
    else if (arg === '--pretty') args.pretty = true;
    else if (arg === '--message-only') args.messageOnly = true;
  }
  return args;
}

function sha(value) { return crypto.createHash('sha256').update(String(value)).digest('hex'); }
function shortHash(value) { return sha(value).slice(0, 24); }
function usd(value) { return Number.isFinite(value) ? `$${Math.round(value).toLocaleString('en-US')}` : 'n/a'; }
function pct(value) { return Number.isFinite(value) ? `${Math.round(value)}%` : 'n/a'; }
function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

function readJson(file, fallback) {
  try { const text = fs.readFileSync(file, 'utf8').trim(); return text ? JSON.parse(text) : fallback; }
  catch (e) { if (e.code === 'ENOENT') return fallback; throw e; }
}
function writeJson(file, value) { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n'); }

function readAddresses() {
  const text = fs.readFileSync(addressesPath, 'utf8');
  const entries = [];
  for (const line of text.split(/\r?\n/)) {
    const clean = line.trim();
    if (!clean || clean.startsWith('#') || !clean.includes('=')) continue;
    const [keyRaw, ...rest] = clean.split('=');
    const key = keyRaw.trim();
    const address = rest.join('=').trim();
    if (key.startsWith('evm_') || key === 'evm2') entries.push({ type: 'evm', key, address });
    else if (key.startsWith('sol_')) entries.push({ type: 'sol', key, address });
  }
  // dedupe repeated Solana addresses without storing them later
  const seen = new Set();
  return entries.filter((item) => {
    const sig = `${item.type}:${item.address.toLowerCase()}`;
    if (seen.has(sig)) return false;
    seen.add(sig);
    return true;
  });
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`${url} failed ${res.status}: ${(await res.text()).slice(0, 160)}`);
  return res.json();
}

async function rpc(url, method, params) {
  const body = JSON.stringify({ jsonrpc: '2.0', id: 1, method, params });
  const data = await fetchJson(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body });
  if (data.error) throw new Error(`${method} failed: ${data.error.message || JSON.stringify(data.error)}`);
  return data.result;
}

async function getPrices() {
  const ids = ['ethereum', 'binancecoin', 'solana'].join(',');
  const data = await fetchJson(`https://api.coingecko.com/api/v3/simple/price?ids=${ids}&vs_currencies=usd`);
  return {
    ethereum: data.ethereum?.usd || 0,
    binancecoin: data.binancecoin?.usd || 0,
    solana: data.solana?.usd || 0,
  };
}

function encodeBalanceOf(address) {
  return '0x70a08231' + address.toLowerCase().replace(/^0x/, '').padStart(64, '0');
}
function hexToNumber(hex, decimals) {
  if (!hex || hex === '0x') return 0;
  return Number(BigInt(hex)) / (10 ** decimals);
}
async function fetchDebankTokenList(address, chainId) {
  const url = `https://api.debank.com/token/balance_list?user_addr=${encodeURIComponent(address)}&chain=${encodeURIComponent(chainId)}&is_all=true`;
  const res = await fetch(url, {
    headers: {
      accept: 'application/json,text/plain,*/*',
      'user-agent': 'Mozilla/5.0 legacy agent portfolio live informer',
      referer: 'https://debank.com/',
    },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error_code) throw new Error(`DeBank ${chainId} failed ${res.status}${data.error_msg ? `: ${data.error_msg}` : ''}`);
  return Array.isArray(data.data) ? data.data : Array.isArray(data) ? data : [];
}

function tokenUsdValue(token) {
  const direct = Number(token.usd_value ?? token.value ?? token.total_value ?? 0);
  if (Number.isFinite(direct) && direct > 0) return direct;
  const amount = Number(token.amount ?? token.balance ?? 0);
  const price = Number(token.price ?? token.usd_price ?? 0);
  return Number.isFinite(amount) && Number.isFinite(price) ? amount * price : 0;
}

async function fallbackEvmChainValue(entry, chain, prices) {
  const result = { nativeUsd: 0, stableUsd: 0, totalUsd: 0, top: [] };
  if (!chain.rpc) return result;
  const balHex = await rpc(chain.rpc, 'eth_getBalance', [entry.address, 'latest']);
  const native = hexToNumber(balHex, 18);
  result.nativeUsd = native * (prices[chain.nativePriceId] || 0);
  result.totalUsd += result.nativeUsd;
  if (result.nativeUsd > 1) result.top.push({ symbol: chain.native, value: result.nativeUsd });
  if (chain.usdc) {
    const call = { to: chain.usdc, data: encodeBalanceOf(entry.address) };
    const usdcHex = await rpc(chain.rpc, 'eth_call', [call, 'latest']);
    result.stableUsd = hexToNumber(usdcHex, chain.usdcDecimals || 6);
    result.totalUsd += result.stableUsd;
    if (result.stableUsd > 1) result.top.push({ symbol: 'USDC', value: result.stableUsd });
  }
  return result;
}

async function evmWalletValue(entry, prices) {
  const totals = { stableUsd: 0, totalUsd: 0, top: [], errors: [], source: 'debank+rpc-fallback' };
  for (const chain of EVM_CHAINS) {
    try {
      const tokens = await fetchDebankTokenList(entry.address, chain.debank);
      let chainTotal = 0;
      for (const token of tokens) {
        const value = tokenUsdValue(token);
        if (!Number.isFinite(value) || value <= 0) continue;
        const symbol = String(token.optimized_symbol || token.symbol || token.name || 'TOKEN').toUpperCase();
        chainTotal += value;
        if (STABLE_SYMBOLS.has(symbol)) totals.stableUsd += value;
        totals.top.push({ symbol, value, chain: chain.id });
      }
      totals.totalUsd += chainTotal;
      await sleep(450);
    } catch (e) {
      totals.errors.push(`${chain.id}:debank:${e.message.slice(0, 80)}`);
      try {
        const fallback = await fallbackEvmChainValue(entry, chain, prices);
        totals.totalUsd += fallback.totalUsd;
        totals.stableUsd += fallback.stableUsd;
        totals.top.push(...fallback.top.map((item) => ({ ...item, chain: chain.id })));
      } catch (fallbackError) {
        totals.errors.push(`${chain.id}:fallback:${fallbackError.message.slice(0, 80)}`);
      }
    }
  }
  totals.top.sort((a, b) => b.value - a.value);
  return totals;
}

async function solanaWalletValue(entry, prices) {
  const result = { solUsd: 0, usdcUsd: 0, pricedTokenUsd: 0, totalUsd: 0, top: [], errors: [] };
  try {
    const bal = await rpc(SOL_RPC, 'getBalance', [entry.address]);
    const sol = (bal.value || 0) / 1e9;
    result.solUsd = sol * (prices.solana || 0);
  } catch (e) { result.errors.push(`sol:${e.message.slice(0, 60)}`); }

  let accounts = [];
  try {
    const tokenProgramId = ['TokenkegQfeZyiNwAJbNb', 'GKPFXCWuBvf9Ss623VQ5DA'].join('');
    const resp = await rpc(SOL_RPC, 'getTokenAccountsByOwner', [entry.address, { programId: tokenProgramId }, { encoding: 'jsonParsed' }]);
    accounts = Array.isArray(resp.value) ? resp.value : [];
  } catch (e) { result.errors.push(`tokens:${e.message.slice(0, 60)}`); }

  const holdings = [];
  for (const account of accounts) {
    const info = account.account?.data?.parsed?.info;
    const mint = info?.mint;
    const amount = Number(info?.tokenAmount?.uiAmount || 0);
    if (!mint || !amount) continue;
    if (mint === USDC_SOL_MINT) result.usdcUsd += amount;
    holdings.push({ mint, amount });
  }

  const priced = [];
  const mints = holdings.map((h) => h.mint).filter((m) => m !== USDC_SOL_MINT);
  for (let i = 0; i < mints.length; i += 50) {
    const ids = mints.slice(i, i + 50).join(',');
    if (!ids) continue;
    try {
      const data = await fetchJson(`https://lite-api.jup.ag/price/v3?ids=${encodeURIComponent(ids)}`);
      for (const h of holdings) {
        const item = data[h.mint];
        const price = Number(item?.usdPrice || item?.price || 0);
        if (price > 0) priced.push({ mint: h.mint, value: h.amount * price, symbol: item.symbol || h.mint.slice(0, 4) });
      }
    } catch (e) { result.errors.push(`jup:${e.message.slice(0, 60)}`); }
  }
  priced.sort((a, b) => b.value - a.value);
  result.pricedTokenUsd = priced.reduce((s, h) => s + h.value, 0);
  result.top = priced.slice(0, 5).map((h) => ({ symbol: h.symbol, value: Math.round(h.value) }));
  result.totalUsd = result.solUsd + result.usdcUsd + result.pricedTokenUsd;
  return result;
}

function categoryFingerprint(summary) {
  const totalBucket = Math.round((summary.totalUsd || 0) / 50) * 50;
  const stablePctBucket = Math.round((summary.stablePct || 0) / 5) * 5;
  const concentrationBucket = Math.round((summary.concentrationPct || 0) / 5) * 5;
  const topSol = summary.solanaTop.map((x) => `${x.symbol}:${Math.round(x.value / 10) * 10}`).join('|');
  return shortHash(JSON.stringify({ totalBucket, stablePctBucket, concentrationBucket, topSol, warnings: summary.warnings }));
}

function buildMessage(summary, change) {
  const lines = ['Портфолио: есть заметное изменение / нужен weekly check.'];
  lines.push('');
  lines.push(`Видимый rough total: ${usd(summary.totalUsd)}`);
  lines.push(`USDC/stables: ${usd(summary.stableUsd)} (${pct(summary.stablePct)})`);
  lines.push(`Концентрация крупнейшего кармана: ${pct(summary.concentrationPct)}`);
  if (summary.evmTop && summary.evmTop.length) lines.push(`EVM top: ${summary.evmTop.map((x) => `${x.symbol} ~${usd(x.value)}`).join(', ')}`);
  if (summary.solanaTop.length) lines.push(`Solana top: ${summary.solanaTop.map((x) => `${x.symbol} ~${usd(x.value)}`).join(', ')}`);
  if (change) lines.push(`Изменение к прошлому live-check: ${change}`);
  lines.push('');
  lines.push('Что проверить:');
  for (const w of summary.warnings.slice(0, 5)) lines.push(`- ${w}`);
  lines.push('- если были DeFi/NFT/LP позиции, перепроверить через полноценный /portfolio, потому что live-check видит только rough liquid/native/token срез');
  return lines.join('\n');
}

async function run(args) {
  const state = readJson(args.state, {});
  const now = new Date().toISOString();
  const addresses = readAddresses();
  const prices = await getPrices();
  const pockets = [];
  const errors = [];

  for (const entry of addresses) {
    if (entry.type === 'evm') {
      const value = await evmWalletValue(entry, prices);
      errors.push(...value.errors);
      pockets.push({ type: 'evm', keyHash: shortHash(entry.key), totalUsd: value.totalUsd, stableUsd: value.stableUsd, top: value.top.slice(0, 8) });
    } else if (entry.type === 'sol') {
      const value = await solanaWalletValue(entry, prices);
      errors.push(...value.errors);
      pockets.push({ type: 'sol', keyHash: shortHash(entry.key), totalUsd: value.totalUsd, stableUsd: value.usdcUsd, top: value.top });
    }
  }

  const totalUsd = pockets.reduce((s, p) => s + p.totalUsd, 0);
  const stableUsd = pockets.reduce((s, p) => s + p.stableUsd, 0);
  const largest = pockets.slice().sort((a, b) => b.totalUsd - a.totalUsd)[0] || { totalUsd: 0 };
  const summary = {
    totalUsd,
    stableUsd,
    stablePct: totalUsd ? stableUsd / totalUsd * 100 : 0,
    concentrationPct: totalUsd ? largest.totalUsd / totalUsd * 100 : 0,
    evmTop: pockets.filter((p) => p.type === 'evm').flatMap((p) => p.top || []).sort((a, b) => b.value - a.value).slice(0, 5),
    solanaTop: pockets.filter((p) => p.type === 'sol').flatMap((p) => p.top || []).sort((a, b) => b.value - a.value).slice(0, 5),
    warnings: [],
    errorsCount: errors.length,
  };
  if (summary.stablePct > 60) summary.warnings.push('stable-доля выглядит очень высокой — сверить с целевой структурой');
  if (summary.concentrationPct > 60) summary.warnings.push('высокая концентрация в одном кармане/кошельке — проверить риск и назначение этой доли');
  if (summary.totalUsd < 1) summary.warnings.push('live-check почти ничего не увидел — возможно, API/источники не покрывают позиции');
  if (errors.length) summary.warnings.push(`часть источников вернула ошибки (${errors.length}) — срез может быть неполным`);
  if (!summary.warnings.length) summary.warnings.push('сверить доли, новые/закрытые позиции и соответствие целевой структуре');

  const fingerprint = categoryFingerprint(summary);
  const firstRun = !state.lastFingerprint;
  const changed = state.lastFingerprint && state.lastFingerprint !== fingerprint;
  const shouldSend = !firstRun && changed;
  const message = shouldSend ? buildMessage(summary, null) : '';

  const nextState = {
    version: 1,
    lastRunAt: now,
    lastFingerprint: fingerprint,
    lastSentAt: shouldSend ? now : (state.lastSentAt || null),
    lastDecision: { sent: shouldSend, reason: firstRun ? 'bootstrap' : changed ? 'changed' : 'no_material_change', errorsCount: errors.length },
  };
  if (!args.dryRun) writeJson(args.state, nextState);

  return { ok: true, dryRun: args.dryRun, checkedAt: now, send: shouldSend, reason: nextState.lastDecision.reason, message, summary: { totalUsd: Math.round(totalUsd), stablePct: Math.round(summary.stablePct), concentrationPct: Math.round(summary.concentrationPct), evmTop: summary.evmTop, solanaTop: summary.solanaTop, errorsCount: errors.length }, privacy: 'state stores only hashes, timestamps and decision metadata; no wallet addresses, balances, token amounts, aggregate totals, raw holdings, or raw snapshot text' };
}

if (require.main === module) {
  const args = parseArgs(process.argv.slice(2));
  run(args).then((result) => {
    if (args.messageOnly) process.stdout.write((result.message || 'NO_REPLY') + '\n');
    else process.stdout.write(JSON.stringify(result, null, args.pretty ? 2 : 0) + '\n');
  }).catch((e) => {
    process.stderr.write(JSON.stringify({ ok: false, error: e.message || String(e) }, null, 2) + '\n');
    process.exit(1);
  });
}
