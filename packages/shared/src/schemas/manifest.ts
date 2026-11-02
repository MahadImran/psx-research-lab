import { z } from 'zod';
import { DailyBarSchema, MarketSnapshotSchema, IndexDataSchema } from './market';

export const DataManifestSchema = z.object({
  manifestVersion: z.literal('1.0.0'),
  generatedAtUtc: z.string().datetime(),
  tradingDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  source: z.string(),
  totalBars: z.number().int().nonnegative(),
  totalSnapshots: z.number().int().nonnegative(),
  totalIndices: z.number().int().nonnegative(),
  payloadSha256: z.string().length(64),
  archivePath: z.string().optional(),
});

export type DataManifest = z.infer<typeof DataManifestSchema>;

export const IngestPayloadSchema = z.object({
  manifest: DataManifestSchema,
  bars: z.array(DailyBarSchema).default([]),
  snapshot: MarketSnapshotSchema.optional(),
  indices: z.array(IndexDataSchema).default([]),
  collectorRunId: z.string(),
  timestamp: z.number().int(), // Unix timestamp (ms or sec)
  nonce: z.string().min(8),
});

export type IngestPayload = z.infer<typeof IngestPayloadSchema>;
