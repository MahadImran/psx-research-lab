import { z } from 'zod';

export const SymbolInfoSchema = z.object({
  symbol: z.string().min(1).max(20).toUpperCase(),
  name: z.string(),
  sector: z.string().optional(),
  listed: z.boolean().default(true),
  isIndex: z.boolean().default(false),
});

export type SymbolInfo = z.infer<typeof SymbolInfoSchema>;

export const DailyBarSchema = z.object({
  source: z.string().min(1),
  symbol: z.string().min(1).toUpperCase(),
  tradingDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Must be YYYY-MM-DD'),
  open: z.number().nonnegative(),
  high: z.number().nonnegative().nullable(), // Nullable because eod() lacks high/low in psx-dps
  low: z.number().nonnegative().nullable(),  // Nullable
  close: z.number().nonnegative(),
  volume: z.number().int().nonnegative(),
  revision: z.number().int().nonnegative().default(0),
  isQuarantined: z.boolean().default(false),
  quarantineReason: z.string().nullable().optional(),
  hash: z.string().min(32),
  fetchedAtUtc: z.string().datetime(),
});

export type DailyBar = z.infer<typeof DailyBarSchema>;

export const SnapshotObservationSchema = z.object({
  symbol: z.string().toUpperCase(),
  current: z.number().nonnegative(),
  change: z.number(),
  changePercent: z.number(),
  high: z.number().nonnegative().nullable().optional(),
  low: z.number().nonnegative().nullable().optional(),
  volume: z.number().int().nonnegative(),
  lastUpdated: z.string().optional(),
});

export type SnapshotObservation = z.infer<typeof SnapshotObservationSchema>;

export const MarketSnapshotSchema = z.object({
  source: z.string(),
  batchId: z.string().uuid(),
  tradingDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  fetchedAtUtc: z.string().datetime(),
  totalSymbols: z.number().int().positive(),
  observations: z.array(SnapshotObservationSchema),
  rawSha256: z.string().length(64),
});

export type MarketSnapshot = z.infer<typeof MarketSnapshotSchema>;

export const IntradayTickSchema = z.object({
  symbol: z.string().toUpperCase(),
  sequenceId: z.number().int().nonnegative(), // Preserves duplicate price/vol identical ticks
  timestampUtc: z.string().datetime(),
  marketTimeKarachi: z.string(),
  price: z.number().positive(),
  volume: z.number().int().nonnegative(),
});

export type IntradayTick = z.infer<typeof IntradayTickSchema>;

export const IndexDataSchema = z.object({
  code: z.string().toUpperCase(),
  current: z.number().positive(),
  change: z.number(),
  changePercent: z.number(),
  volume: z.number().int().nonnegative(),
  tradingDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  fetchedAtUtc: z.string().datetime(),
});

export type IndexData = z.infer<typeof IndexDataSchema>;
