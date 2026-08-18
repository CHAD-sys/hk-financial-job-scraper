import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { AdminOperationsDashboard } from '../../api/client'
import OperationsCenter from './OperationsCenter'

const DATA: AdminOperationsDashboard = {
  generated_at: '2026-08-10T10:30:00+08:00',
  run: {
    run_id: '123', scraped_date: '2026-08-10', status: 'warning',
    source_run_url: 'https://github.test/runs/123',
    phases: [
      { key: 'restore', label: 'Restore', status: 'success', duration_seconds: 5 },
      { key: 'deepseek', label: 'DeepSeek', status: 'warning', duration_seconds: 65 },
    ],
  },
  quality_gates: [
    { key: 'descriptions', label: 'Description coverage', value: 98.2, unit: '%', status: 'pass', detail: '12 listings are missing descriptions.' },
  ],
  source_health: [
    { source: 'workday', companies: 5, successful: 5, zero_results: 0, failed: 0, roles: 120, runtime_seconds: 90, failure_rate_pct: 0, hiring_rate_pct: 100, status: 'healthy', tracking_available: true, roles_found: 120, active_roles: null },
  ],
  ai_cost: {
    calls: 14, roles_processed: 14, estimated_cost_usd: 0.0123,
    cache_hit_tokens: 1000, cache_miss_tokens: 500, completion_tokens: 200,
    backlog: 3, daily_limit: 300, tracking_available: true,
  },
  publication: {
    source_run_id: '123', snapshot_sha256: 'a'.repeat(64), source_run_url: null,
    received_at: '2026-08-10T02:20:00Z', active_jobs: 5373, restore_source: 'railway',
  },
  recommendations: {
    impressions: 200, clicks: 40, click_through_pct: 20, saves: 8,
    more_like: 6, dismissals: 4, wrong_reason: 1, seekers_reached: 15,
    eligible_seekers: 20, coverage_pct: 75, tracking_available: true,
    window_started_at: '2026-08-01T00:00:00Z', window_ended_at: '2026-08-10T00:00:00Z',
  },
  alerts: [{ severity: 'warning', title: 'DeepSeek needs review', detail: 'One optional phase warned.' }],
}

describe('OperationsCenter', () => {
  it('shows all seven administrator decision areas with real values', () => {
    render(<OperationsCenter data={DATA} />)

    expect(screen.getByRole('list', { name: 'Pipeline phase timeline' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Data-quality gates' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'AI cost control' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Source health' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Publication safety' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Recommendation health' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Actionable alerts' })).toBeInTheDocument()
    expect(screen.getByText('$0.0123')).toBeInTheDocument()
    expect(screen.getByText('5,373')).toBeInTheDocument()
    const sourceTable = screen.getByRole('table')
    expect(within(sourceTable).getByText('Workday')).toBeInTheDocument()
    expect(within(sourceTable).getByText('100%')).toBeInTheDocument()
  })

  it('states when exact telemetry has not started instead of inventing success', () => {
    render(<OperationsCenter data={{
      ...DATA,
      run: { phases: [{ key: 'restore', label: 'Restore', status: 'not_recorded', duration_seconds: null }] },
      ai_cost: { ...DATA.ai_cost!, tracking_available: false, calls: 0, estimated_cost_usd: 0 },
      source_health: DATA.source_health!.map(source => ({ ...source, tracking_available: false, roles_found: null, active_roles: 120, failure_rate_pct: null, hiring_rate_pct: null, status: 'not_recorded' })),
      recommendations: { ...DATA.recommendations!, tracking_available: false },
      alerts: [],
    }} />)
    expect(screen.getByText('Detailed telemetry begins with the next run')).toBeInTheDocument()
    expect(screen.getAllByText('Awaiting telemetry').length).toBeGreaterThan(0)
    expect(screen.getByText(/Insufficient telemetry to assess/)).toBeInTheDocument()
    expect(screen.queryByText('$0.0000')).not.toBeInTheDocument()
  })

  it('omits AI cost control entirely for admins the backend withheld it from', () => {
    render(<OperationsCenter data={{ ...DATA, ai_cost: null }} />)

    expect(screen.queryByRole('heading', { name: 'AI cost control' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Data-quality gates' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Source health' })).toBeInTheDocument()
  })

  it('omits Source health, Publication safety and Recommendation health for an ordinary admin', () => {
    render(<OperationsCenter data={{
      ...DATA,
      ai_cost: null,
      source_health: null,
      publication: null,
      recommendations: null,
    }} />)

    expect(screen.queryByRole('heading', { name: 'AI cost control' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Source health' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Publication safety' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Recommendation health' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Data-quality gates' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Actionable alerts' })).toBeInTheDocument()
  })

  it('shows Publication safety and Recommendation health for an Ultimate Admin even with a zero publication receipt', () => {
    render(<OperationsCenter data={{ ...DATA, publication: null }} />)

    expect(screen.getByRole('heading', { name: 'Publication safety' })).toBeInTheDocument()
    expect(screen.getByText('No checksummed Railway publication receipt is available yet.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Recommendation health' })).toBeInTheDocument()
  })
})
