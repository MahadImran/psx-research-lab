import { z } from 'zod';

export const HealthStatusSchema = z.object({
  status: z.enum(['HEALTHY', 'DEGRADED', 'DOWN', 'STALE']),
  marketStatus: z.enum(['OPEN', 'CLOSED', 'PRE_OPEN', 'BREAK']),
  lastSuccessfulIngestUtc: z.string().datetime().nullable(),
  lastAttemptUtc: z.string().datetime().nullable(),
  upstreamRequests24h: z.number().int().nonnegative(),
  remainingUpstreamRequests24h: z.number().int().nonnegative(),
  isCircuitBreakerTripped: z.boolean(),
  cooldownUntilUtc: z.string().datetime().nullable(),
  activeDataVersion: z.string(),
  staleBadge: z.boolean(),
});

export type HealthStatus = z.infer<typeof HealthStatusSchema>;
