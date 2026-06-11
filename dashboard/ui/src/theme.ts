/* Shared chart styling — kept out of components.tsx so that file only exports
   React components (satisfies react-refresh/only-export-components). */

export const CHART_STYLE = {
  tooltip: {
    contentStyle: {
      background: 'var(--panel-alt)', border: '1px solid var(--border)',
      fontSize: 11, fontFamily: "'JetBrains Mono', monospace",
    },
    labelStyle: { color: 'var(--text-dim)' },
    itemStyle:  { color: 'var(--text)' },
  },
  grid:     { stroke: '#252a33', strokeDasharray: '2 4' },
  axis:     { tick: { fill: '#3d4450', fontSize: 9 } },
  green:    '#00e87b',
  red:      '#ff3e3e',
  blue:     '#4da6ff',
}
