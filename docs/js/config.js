// Varsayılan ayarlar — Python sürümündeki config.yaml karşılığı.
// Kullanıcı değişiklikleri localStorage'da saklanır (Ayarlar sekmesi).

export const DEFAULTS = {
  symbols: ['1000SHIBUSDT', 'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'DOGEUSDT'],
  primarySymbol: '1000SHIBUSDT',

  timeframes: { ltf: '15m', mtf: '1h', htf: '4h', klinesLimit: 400 },

  data: {
    depthLimit: 100,
    aggTradesLimit: 1000,
    // Mobil veri tasarrufu: her sayfa ~350 KB. 2 sayfa ≈ 2000 işlem.
    aggTradesPages: 2,
    spotAggTradesPages: 1,
  },

  trend: {
    emaPeriods: [20, 50, 100, 200],
    rsiPeriod: 14,
    macd: { fast: 12, slow: 26, signal: 9 },
    atrPeriod: 14,
    adxPeriod: 14,
    supertrend: { period: 10, multiplier: 3.0 },
    swingLookback: 3,
  },

  smartMoney: {
    sweepWickRatio: 0.55,
    sweepVolumeMult: 1.4,
    sweepLookback: 60,
    fvgMinSizeAtr: 0.15,
    fvgMaxAge: 80,
    obDisplacementAtr: 1.0,
    maxItems: 6,
  },

  derivatives: {
    fundingHistoryLimit: 30,
    lsRatioPeriod: '1h',
    lsRatioLimit: 24,
    takerRatioPeriod: '5m',
    takerRatioLimit: 24,
  },

  whale: {
    tiers: [100000, 250000, 500000, 1000000],
    autoScale: true,
    autoMinHits: 5,
    autoPercentile: 99.0,
    minTierFloor: 5000,
    icebergMinRepeats: 5,
    icebergQtyTolerance: 0.01,
    icebergWindowSeconds: 300,
  },

  orderbook: {
    wallMultiplier: 4.0,
    imbalanceDepthPct: 0.5,
    spoofMinNotional: 150000,
    spoofVanishPct: 0.65,
  },

  risk: {
    accountSizeUsdt: 1000,
    riskPerTradePct: 1.0,
    maxLeverage: 10,
    highVolatilityAtrPct: 3.0,
    extremeFunding: 0.05,
    crowdedLsRatio: 2.5,
  },

  scoring: {
    weights: {
      trend: 18, open_interest: 15, funding: 10, cvd: 12, rsi: 6,
      macd: 8, orderbook: 14, whale: 11, liquidation: 8, smart_money: 12,
    },
    thresholds: {
      strongLong: 75, long: 62, weakLong: 55,
      weakShort: 45, short: 38, strongShort: 25,
    },
  },

  setup: {
    minScoreForSetup: 55,
    stopAtrMultiplier: 1.5,
    tpRMultiples: [1.5, 2.5, 4.0],
    entryPullbackAtr: 0.35,
    minRr: 1.2,
  },

  market: {
    quoteAsset: 'USDT',
    minQuoteVolumeUsdt: 3_000_000,
    oiEnrichTop: 150,
    oiConcurrency: 5,
    deepScanTop: 10,
    alwaysIncludeWatchlist: true,
    extremeFundingPct: 0.05,
    deepScanAggPages: 1,
  },
};

const KEY = 'kripto.config.v1';

function deepMerge(base, override) {
  const out = Array.isArray(base) ? [...base] : { ...base };
  for (const [k, v] of Object.entries(override || {})) {
    if (v && typeof v === 'object' && !Array.isArray(v) && base[k] && typeof base[k] === 'object' && !Array.isArray(base[k])) {
      out[k] = deepMerge(base[k], v);
    } else {
      out[k] = v;
    }
  }
  return out;
}

// structuredClone iOS 15.4 öncesinde yok — JSON ile yedekliyoruz
const clone = (o) => (typeof structuredClone === 'function'
  ? structuredClone(o) : JSON.parse(JSON.stringify(o)));

export function loadConfig() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? deepMerge(DEFAULTS, JSON.parse(raw)) : clone(DEFAULTS);
  } catch {
    return clone(DEFAULTS);
  }
}

export function saveConfig(patch) {
  const cur = loadConfig();
  const next = deepMerge(cur, patch);
  // Varsayılanlardan farkı değil, tamamını saklıyoruz — basit ve yeterli
  localStorage.setItem(KEY, JSON.stringify(next));
  return next;
}

export function resetConfig() {
  localStorage.removeItem(KEY);
  return clone(DEFAULTS);
}
