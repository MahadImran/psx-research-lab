import { describe, it, expect } from 'vitest';
import { TIMEZONE, AI_QUOTA, MAX_UPSTREAM_REQUESTS_PER_24H } from '@psx/shared';

describe('Web App Constants & Terminal UI Defaults', () => {
  it('loads timezone and limits correctly', () => {
    expect(TIMEZONE).toBe('Asia/Karachi');
    expect(MAX_UPSTREAM_REQUESTS_PER_24H).toBe(250);
    expect(AI_QUOTA.GLOBAL_DAILY_LIMIT).toBe(50);
  });
});
