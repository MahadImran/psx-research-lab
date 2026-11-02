import React, { useState } from 'react';
import { TIMEZONE, AI_QUOTA, MAX_UPSTREAM_REQUESTS_PER_24H } from '@psx/shared';

export function App() {
  const [activeTab, setActiveTab] = useState<'market' | 'strategy' | 'health'>('market');

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* High-density Terminal Top Bar */}
      <header
        style={{
          borderBottom: '1px solid #30363d',
          padding: '8px 16px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: '#161b22',
          fontSize: '13px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <strong style={{ color: '#58a6ff', letterSpacing: '1px' }}>PSX RESEARCH LAB</strong>
          <span
            style={{
              padding: '2px 8px',
              borderRadius: '4px',
              backgroundColor: '#1f6feb22',
              color: '#58a6ff',
              border: '1px solid #1f6feb',
            }}
          >
            STAGING (ACCESS PROTECTED)
          </span>
          <span style={{ color: '#8b949e' }}>Market Time: {TIMEZONE}</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <span style={{ color: '#238636', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: '#238636',
                display: 'inline-block',
              }}
            />
            DATA CONFIDENCE: HIGH
          </span>
          <span style={{ color: '#8b949e' }}>
            Upstream Fuse: {MAX_UPSTREAM_REQUESTS_PER_24H} req/24h
          </span>
          <span style={{ color: '#8b949e' }}>
            AI Quota: {AI_QUOTA.GLOBAL_DAILY_LIMIT}/day
          </span>
        </div>
      </header>

      {/* Navigation tabs */}
      <div
        style={{
          borderBottom: '1px solid #30363d',
          padding: '4px 16px',
          display: 'flex',
          gap: '8px',
          backgroundColor: '#0d1117',
        }}
      >
        {(['market', 'strategy', 'health'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              background: activeTab === tab ? '#21262d' : 'transparent',
              color: activeTab === tab ? '#f0f6fc' : '#8b949e',
              border: activeTab === tab ? '1px solid #30363d' : '1px solid transparent',
              borderRadius: '6px',
              padding: '6px 12px',
              cursor: 'pointer',
              textTransform: 'uppercase',
              fontSize: '12px',
              fontWeight: 600,
            }}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Main Terminal Viewport */}
      <main style={{ flex: 1, padding: '16px' }}>
        {activeTab === 'market' && (
          <div>
            <h2 style={{ fontSize: '18px', marginBottom: '12px' }}>Market Overview (Karachi)</h2>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
                gap: '12px',
              }}
            >
              <div style={{ border: '1px solid #30363d', padding: '16px', borderRadius: '6px' }}>
                <div style={{ color: '#8b949e', fontSize: '12px' }}>KSE 100 INDEX</div>
                <div style={{ fontSize: '24px', fontWeight: 'bold', margin: '4px 0' }}>85,250.12</div>
                <div style={{ color: '#238636', fontSize: '13px' }}>+450.21 (+0.53%)</div>
              </div>
              <div style={{ border: '1px solid #30363d', padding: '16px', borderRadius: '6px' }}>
                <div style={{ color: '#8b949e', fontSize: '12px' }}>OGDC (Oil & Gas Dev Co)</div>
                <div style={{ fontSize: '24px', fontWeight: 'bold', margin: '4px 0' }}>136.20 PKR</div>
                <div style={{ color: '#238636', fontSize: '13px' }}>+1.40 (+1.04%)</div>
              </div>
              <div style={{ border: '1px solid #30363d', padding: '16px', borderRadius: '6px' }}>
                <div style={{ color: '#8b949e', fontSize: '12px' }}>ENGRO (Engro Corp)</div>
                <div style={{ fontSize: '24px', fontWeight: 'bold', margin: '4px 0' }}>285.50 PKR</div>
                <div style={{ color: '#da3633', fontSize: '13px' }}>-2.10 (-0.73%)</div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'strategy' && (
          <div>
            <h2 style={{ fontSize: '18px', marginBottom: '12px' }}>Deterministic Strategy Lab</h2>
            <p style={{ color: '#8b949e', fontSize: '13px' }}>
              Deterministic backtesting engine runs 100% in-browser via Web Worker. AI compiles natural
              language to versioned DSL; math is strictly reproducible.
            </p>
          </div>
        )}

        {activeTab === 'health' && (
          <div>
            <h2 style={{ fontSize: '18px', marginBottom: '12px' }}>Data Provenance & Health</h2>
            <div style={{ border: '1px solid #30363d', padding: '16px', borderRadius: '6px' }}>
              <div>Primary Collector: <strong>psx-dps (Umair Sandhu)</strong></div>
              <div>Secondary Fallback: <strong>psxdata (Alpha API)</strong></div>
              <div>Historical Bootstrap: <strong>PSXpert (Quarantined audit pending)</strong></div>
              <div style={{ marginTop: '8px', color: '#8b949e', fontSize: '12px' }}>
                Persistent lease active. Zero-dollar cloud architecture.
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
export default App;
