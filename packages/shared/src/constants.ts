/**
 * PSX Research Lab — Core Operational & Market Constants
 * Timezone: Asia/Karachi (PKT, UTC+5)
 * Cloud: Cloudflare Workers Free + GitHub Actions (Ephemeral Linux)
 */

export const TIMEZONE = 'Asia/Karachi';

// Upstream PSX rate limits and safety fuses
export const MAX_UPSTREAM_REQUESTS_PER_24H = 250; // Hard app-level circuit breaker
export const MIN_REQUEST_INTERVAL_SECONDS = 1.0;  // Fair use pause between requests
export const MAX_CONSECUTIVE_ERRORS = 3;         // Trip cooldown after 3 errors
export const DEFAULT_COOLDOWN_SECONDS = 300;     // 5-minute pause on 429/503

// Community AI Quotas (Spend limiter for Gemini Free Tier)
export const AI_QUOTA = {
  GLOBAL_DAILY_LIMIT: 50,
  VISITOR_DAILY_LIMIT: 5,
  MIN_INTERVAL_SECONDS: 30,
  MAX_CONCURRENT_PER_USER: 1,
  MAX_PROMPT_TOKENS: 8000,
  MAX_OUTPUT_TOKENS: 1500,
  RESET_TIMEZONE: 'America/Los_Angeles', // Aligns with Gemini RPD reset
  MODEL_NAME: 'gemini-3.5-flash-lite',
} as const;

// Market Trading Hours (PKT: Asia/Karachi)
// Monday to Thursday: 09:15 - 15:30
// Friday: Session 1 (09:15 - 12:00), Session 2 (14:30 - 16:30)
export const TRADING_HOURS = {
  REGULAR: {
    START: '09:15',
    END: '15:30',
  },
  FRIDAY_SESSION_1: {
    START: '09:15',
    END: '12:00',
  },
  FRIDAY_SESSION_2: {
    START: '14:30',
    END: '16:30',
  },
} as const;

// Standard symbols tracked for bounded probe and high-liquidity analysis
export const CORE_BENCHMARK_SYMBOLS = ['OGDC', 'ENGRO', 'HUBC', 'LUCK', 'FFC'] as const;
export const CORE_INDICES = ['KSE100', 'KSE30', 'KMI30', 'ALLSHR'] as const;
