/* Recharts wrappers themed with the design tokens. Every chart also exposes its data as text
   (aria-label / list) so the numbers are available to screen readers. */
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, PolarAngleAxis, RadialBar, RadialBarChart, ResponsiveContainer, Tooltip as ReTooltip, XAxis, YAxis } from 'recharts'

import { PALETTE } from '@/lib/palette'
import { cn } from '@/lib/utils'

const tooltipStyle = {
  contentStyle: { background: 'var(--popover)', border: '1px solid var(--border)', borderRadius: 10, fontSize: 12, color: 'var(--popover-foreground)', boxShadow: '0 8px 24px rgb(0 0 0 / 0.12)' },
  labelStyle: { color: 'var(--muted-foreground)', fontWeight: 600, marginBottom: 4 },
  itemStyle: { color: 'var(--popover-foreground)', padding: 0 },
  cursor: { fill: 'color-mix(in oklch, var(--muted) 70%, transparent)' },
}

export function BarList({ items, max, formatValue, className, colorBy }: {
  items: { label: string; value: number; hint?: string }[]
  max?: number
  formatValue?: (v: number) => string
  className?: string
  colorBy?: (label: string, index: number) => string
}) {
  const top = max ?? Math.max(1, ...items.map((i) => i.value))
  return (
    <ul className={cn('space-y-2', className)}>
      {items.map((item, i) => (
        <li key={item.label} className="space-y-1">
          <div className="flex items-baseline justify-between gap-2 text-sm">
            <span className="truncate">{item.label}</span>
            <span className="text-muted-foreground shrink-0 tabular-nums text-xs">
              {formatValue ? formatValue(item.value) : item.value.toLocaleString()}
              {item.hint ? <span className="ml-1.5 opacity-70">{item.hint}</span> : null}
            </span>
          </div>
          <div className="bg-muted h-2 overflow-hidden rounded-full" aria-hidden>
            <div className="h-full rounded-full transition-[width] duration-700" style={{ width: `${Math.max(2, (item.value / top) * 100)}%`, background: colorBy ? colorBy(item.label, i) : PALETTE[i % PALETTE.length] }} />
          </div>
        </li>
      ))}
    </ul>
  )
}

export function DonutChart({ data, height = 220, centerLabel, centerValue }: { data: { label: string; value: number; color?: string }[]; height?: number; centerLabel?: string; centerValue?: string | number }) {
  const total = data.reduce((s, d) => s + d.value, 0)
  return (
    <div className="relative" role="img" aria-label={data.map((d) => `${d.label}: ${d.value}`).join(', ')}>
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="label" innerRadius="62%" outerRadius="92%" paddingAngle={1.5} stroke="var(--card)" strokeWidth={2} isAnimationActive>
            {data.map((d, i) => (
              <Cell key={d.label} fill={d.color ?? PALETTE[i % PALETTE.length]} />
            ))}
          </Pie>
          <ReTooltip {...tooltipStyle} formatter={(v) => [`${v} (${total ? Math.round((Number(v) / total) * 100) : 0}%)`, '']} />
        </PieChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <div className="text-2xl font-semibold tabular-nums">{centerValue ?? total}</div>
        {centerLabel ? <div className="text-muted-foreground text-xs">{centerLabel}</div> : null}
      </div>
    </div>
  )
}

export function Legendary({ items }: { items: { label: string; value?: number | string; color?: string }[] }) {
  return (
    <ul className="grid grid-cols-1 gap-1.5 text-xs sm:grid-cols-2">
      {items.map((d, i) => (
        <li key={d.label} className="flex items-center gap-2">
          <span className="size-2.5 shrink-0 rounded-sm" style={{ background: d.color ?? PALETTE[i % PALETTE.length] }} aria-hidden />
          <span className="truncate">{d.label}</span>
          {d.value !== undefined ? <span className="text-muted-foreground ml-auto tabular-nums">{d.value}</span> : null}
        </li>
      ))}
    </ul>
  )
}

export function TrendChart({ data, series, xKey = 'bucket', height = 260, stacked = false }: {
  data: Record<string, unknown>[]
  series: { key: string; label: string; color?: string }[]
  xKey?: string
  height?: number
  stacked?: boolean
}) {
  return (
    <div role="img" aria-label={`Trend chart with ${data.length} points for ${series.map((s) => s.label).join(', ')}`}>
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <defs>
            {series.map((s, i) => (
              <linearGradient key={s.key} id={`grad-${s.key.replace(/[^a-zA-Z0-9]/g, '')}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={s.color ?? PALETTE[i % PALETTE.length]} stopOpacity={0.28} />
                <stop offset="100%" stopColor={s.color ?? PALETTE[i % PALETTE.length]} stopOpacity={0.02} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={false} minTickGap={24} />
          <YAxis tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={false} allowDecimals={false} />
          <ReTooltip {...tooltipStyle} />
          <Legend wrapperStyle={{ fontSize: 12 }} iconType="circle" iconSize={8} />
          {series.map((s, i) => (
            <Area key={s.key} type="monotone" dataKey={s.key} name={s.label} stackId={stacked ? '1' : undefined} stroke={s.color ?? PALETTE[i % PALETTE.length]} strokeWidth={2} fill={`url(#grad-${s.key.replace(/[^a-zA-Z0-9]/g, '')})`} />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

export function GroupedBarChart({ data, bars, xKey, height = 260, layout = 'horizontal', stacked = false, valueFormatter }: {
  data: Record<string, unknown>[]
  bars: { key: string; label: string; color?: string }[]
  xKey: string
  height?: number
  layout?: 'horizontal' | 'vertical'
  stacked?: boolean
  valueFormatter?: (v: number) => string
}) {
  const vertical = layout === 'vertical'
  return (
    <div role="img" aria-label={`Bar chart: ${bars.map((b) => b.label).join(', ')}`}>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout={vertical ? 'vertical' : 'horizontal'} margin={{ top: 8, right: 12, bottom: 0, left: vertical ? 8 : -18 }} barCategoryGap="22%">
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" horizontal={!vertical} vertical={vertical} />
          {vertical ? (
            <>
              <XAxis type="number" tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={false} tickFormatter={valueFormatter} />
              <YAxis type="category" dataKey={xKey} width={132} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={false} />
            </>
          ) : (
            <>
              <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={false} interval={0} />
              <YAxis tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={false} tickFormatter={valueFormatter} />
            </>
          )}
          <ReTooltip {...tooltipStyle} formatter={(v) => (valueFormatter ? valueFormatter(Number(v)) : String(v))} />
          {bars.length > 1 ? <Legend wrapperStyle={{ fontSize: 12 }} iconType="circle" iconSize={8} /> : null}
          {bars.map((b, i) => (
            <Bar key={b.key} dataKey={b.key} name={b.label} stackId={stacked ? 's' : undefined} fill={b.color ?? PALETTE[i % PALETTE.length]} radius={stacked ? 0 : vertical ? [0, 4, 4, 0] : [4, 4, 0, 0]} maxBarSize={36} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/** Radial gauge for the verification score (0-100). */
export function ScoreGauge({ score, threshold = 80, size = 150 }: { score: number | null | undefined; threshold?: number; size?: number }) {
  const value = Math.max(0, Math.min(100, score ?? 0))
  const color = score === null || score === undefined ? 'var(--muted-foreground)' : value >= threshold ? 'var(--success)' : value >= threshold - 15 ? 'var(--warning)' : 'var(--destructive)'
  return (
    <div className="relative" style={{ width: size, height: size }} role="img" aria-label={`Verification score ${Math.round(value)} of 100, threshold ${threshold}`}>
      <ResponsiveContainer width="100%" height="100%">
        <RadialBarChart innerRadius="78%" outerRadius="100%" data={[{ value }]} startAngle={220} endAngle={-40}>
          <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
          <RadialBar dataKey="value" cornerRadius={10} fill={color} background={{ fill: 'var(--muted)' }} isAnimationActive />
        </RadialBarChart>
      </ResponsiveContainer>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div className="text-3xl font-semibold tabular-nums" style={{ color }}>
          {score === null || score === undefined ? '—' : Math.round(value)}
        </div>
        <div className="text-muted-foreground text-[11px]">of 100 · pass ≥ {threshold}</div>
      </div>
    </div>
  )
}
