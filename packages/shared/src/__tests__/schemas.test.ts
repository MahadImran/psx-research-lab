import { describe, it, expect } from 'vitest';
import {
  DailyBarSchema,
  MarketSnapshotSchema,
  IntradayTickSchema,
  ExperimentSpecSchema,
  DataManifestSchema,
  IngestPayloadSchema,
  MAX_UPSTREAM_REQUESTS_PER_24H,
} from '../index';

describe('Shared Schemas & Contracts', () => {
  it('validates a DailyBar with nullable high and low', () => {
    const validBar = {
      source: 'psx-dps',
      symbol: 'OGDC',
      tradingDate: '2026-10-30',
      open: 135.5,
      high: null, // eod() in psx-dps lacks high/low
      low: null,
      close: 136.2,
      volume: 1_250_000,
      revision: 0,
      isQuarantined: false,
      hash: 'a'.repeat(64),
      fetchedAtUtc: new Date().toISOString(),
    };

    const parsed = DailyBarSchema.safeParse(validBar);
    expect(parsed.success).toBe(true);
  });

  it('rejects a DailyBar with invalid date format', () => {
    const invalidBar = {
      source: 'psx-dps',
      symbol: 'OGDC',
      tradingDate: '30-10-2026', // Bad format
      open: 100,
      high: 105,
      low: 99,
      close: 102,
      volume: 500,
      hash: 'a'.repeat(64),
      fetchedAtUtc: new Date().toISOString(),
    };

    const parsed = DailyBarSchema.safeParse(invalidBar);
    expect(parsed.success).toBe(false);
  });

  it('validates an IntradayTick with sequenceId to preserve identical ticks', () => {
    const tick = {
      symbol: 'ENGRO',
      sequenceId: 42,
      timestampUtc: new Date().toISOString(),
      marketTimeKarachi: '11:45:02',
      price: 285.5,
      volume: 500,
    };
    const parsed = IntradayTickSchema.safeParse(tick);
    expect(parsed.success).toBe(true);
  });

  it('validates an ExperimentSpec matching whitelisted DSL', () => {
    const spec = {
      version: '1.0.0',
      name: 'SMA Cross on OGDC and ENGRO',
      universe: ['OGDC', 'ENGRO'],
      benchmark: 'KSE100',
      dateRange: {
        startDate: '2025-01-01',
        endDate: '2026-10-31',
      },
      initialCapitalPkr: 500_000,
      entrySignal: {
        operator: 'SMA_CROSS',
        parameters: { fast: 20, slow: 50 },
      },
      execution: {
        timing: 'NEXT_OPEN',
        slippageBps: 15,
        commissionPercent: 0.15,
      },
      reinvestDividends: true,
    };

    const parsed = ExperimentSpecSchema.safeParse(spec);
    expect(parsed.success).toBe(true);
  });

  it('rejects an ExperimentSpec with non-whitelisted operator', () => {
    const spec = {
      version: '1.0.0',
      name: 'Unsafe Python Code Exec',
      universe: ['OGDC'],
      dateRange: {
        startDate: '2025-01-01',
        endDate: '2026-10-31',
      },
      entrySignal: {
        operator: 'EXECUTE_ARBITRARY_CODE', // Must be rejected!
        parameters: { code: 'import os; os.system("rm -rf /")' },
      },
    };

    const parsed = ExperimentSpecSchema.safeParse(spec);
    expect(parsed.success).toBe(false);
  });

  it('enforces 250 requests rolling 24h budget constant', () => {
    expect(MAX_UPSTREAM_REQUESTS_PER_24H).toBe(250);
  });
});
