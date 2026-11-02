import { z } from 'zod';

export const WhitelistedSignalOperator = z.enum([
  'BUY_HOLD',
  'DCA',
  'SMA_CROSS',
  'EMA_CROSS',
  'RSI',
  'DIP_BUY',
  'REBALANCE',
  'STOP_LOSS_TRAILING',
]);

export type SignalOperator = z.infer<typeof WhitelistedSignalOperator>;

export const ExecutionRuleSchema = z.object({
  timing: z.enum(['NEXT_OPEN', 'CLOSE', 'NEXT_CLOSE']).default('NEXT_OPEN'),
  slippageBps: z.number().min(0).max(500).default(10), // Basis points
  commissionPercent: z.number().min(0).max(5).default(0.15), // e.g. 0.15% brokerage + taxes
  maxParticipationRate: z.number().min(0).max(1).default(0.1), // Max 10% of daily volume
});

export const SignalConditionSchema = z.object({
  operator: WhitelistedSignalOperator,
  parameters: z.record(z.string(), z.union([z.number(), z.string(), z.boolean()])),
});

export const ExperimentSpecSchema = z.object({
  version: z.literal('1.0.0'),
  name: z.string().min(1).max(100),
  description: z.string().max(500).optional(),
  universe: z.array(z.string().toUpperCase()).min(1).max(50),
  benchmark: z.string().toUpperCase().default('KSE100'),
  dateRange: z.object({
    startDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    endDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  }),
  initialCapitalPkr: z.number().positive().default(100_000),
  cashflows: z.array(
    z.object({
      date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
      amountPkr: z.number(),
    })
  ).default([]),
  entrySignal: SignalConditionSchema,
  exitSignal: SignalConditionSchema.optional(),
  execution: ExecutionRuleSchema.default({}),
  reinvestDividends: z.boolean().default(true),
});

export type ExperimentSpec = z.infer<typeof ExperimentSpecSchema>;
