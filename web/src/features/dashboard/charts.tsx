/**
 * Small, dependency-free SVG charts for the dashboard (S-D01, S-D02, S-D06). Plain SVG rather
 * than a charting library — this app has none, and three simple charts don't earn one. Each bar
 * carries a native <title> tooltip (no extra JS state) and every chart is backed by a plain
 * table below it, so nothing here is color-only.
 */

const BAR_H = 28;
const GAP = 10;

function formatNumber(n: number): string {
  return n.toLocaleString("en-US");
}

/** A horizontal funnel: each stage is the same color, only the length encodes the count, since
 * every bar is the same metric (a count of people) at a later stage of the same pipeline. */
export function FunnelChart({ stages }: { stages: { label: string; value: number }[] }) {
  const max = Math.max(1, ...stages.map((s) => s.value));
  const width = 480;
  const labelW = 150;
  const trackW = width - labelW - 50;
  const height = stages.length * (BAR_H + GAP);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img" aria-label="Enrolment funnel">
      {stages.map((stage, i) => {
        const y = i * (BAR_H + GAP);
        const w = Math.max(2, (stage.value / max) * trackW);
        return (
          <g key={stage.label}>
            <text x={0} y={y + BAR_H / 2 + 4} className="chart-label">
              {stage.label}
            </text>
            <rect x={labelW} y={y} width={trackW} height={BAR_H} rx={4} className="chart-track" />
            <rect x={labelW} y={y} width={w} height={BAR_H} rx={4} className="chart-bar-accent">
              <title>{`${stage.label}: ${formatNumber(stage.value)}`}</title>
            </rect>
            <text x={labelW + trackW + 8} y={y + BAR_H / 2 + 4} className="chart-value">
              {formatNumber(stage.value)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export interface AttritionGroup {
  label: string;
  retained: number;
  lost: number;
}

/** A stacked bar per programme/cohort: retained (good) vs. lost to withdrawal or dismissal
 * (critical) — a status pair, so it uses the status colors, not a categorical hue. */
export function AttritionChart({ groups }: { groups: AttritionGroup[] }) {
  const max = Math.max(1, ...groups.map((g) => g.retained + g.lost));
  const width = 560;
  const barW = Math.max(18, Math.min(48, Math.floor((width - 40) / Math.max(1, groups.length)) - 8));
  const chartH = 180;
  const gap = Math.max(8, Math.floor((width - 40 - groups.length * barW) / Math.max(1, groups.length)));
  return (
    <>
      <svg viewBox={`0 0 ${width} ${chartH + 40}`} width="100%" role="img" aria-label="Retention and attrition by cohort">
        {groups.map((g, i) => {
          const total = g.retained + g.lost;
          const x = 40 + i * (barW + gap);
          const retainedH = (g.retained / max) * chartH;
          const lostH = (g.lost / max) * chartH;
          return (
            <g key={g.label}>
              <rect
                x={x}
                y={chartH - retainedH}
                width={barW}
                height={retainedH}
                rx={3}
                className="chart-bar-good"
              >
                <title>{`${g.label} retained: ${formatNumber(g.retained)}`}</title>
              </rect>
              <rect
                x={x}
                y={chartH - retainedH - lostH - (lostH > 0 ? 2 : 0)}
                width={barW}
                height={lostH}
                rx={3}
                className="chart-bar-critical"
              >
                <title>{`${g.label} lost (withdrawn or dismissed): ${formatNumber(g.lost)}`}</title>
              </rect>
              <text x={x + barW / 2} y={chartH + 16} textAnchor="middle" className="chart-label-small">
                {g.label}
              </text>
              <text x={x + barW / 2} y={chartH - retainedH - lostH - 6} textAnchor="middle" className="chart-value-small">
                {total}
              </text>
            </g>
          );
        })}
        <line x1={40} y1={chartH} x2={width - 10} y2={chartH} className="chart-axis" />
      </svg>
      <p className="chart-legend">
        <span className="chart-swatch chart-bar-good" /> Retained
        <span className="chart-swatch chart-bar-critical" /> Lost to withdrawal or dismissal
      </p>
    </>
  );
}

export interface FeeGroup {
  label: string;
  charged: number;
  collected: number;
}

/** Two bars per term, same axis, same unit (GYD) — grouped, never a second axis for the rate. */
export function FeeCollectionChart({ groups }: { groups: FeeGroup[] }) {
  const max = Math.max(1, ...groups.map((g) => Math.max(g.charged, g.collected)));
  const width = 560;
  const pairW = Math.max(28, Math.min(70, Math.floor((width - 40) / Math.max(1, groups.length)) - 10));
  const barW = pairW / 2 - 2;
  const chartH = 180;
  const gap = Math.max(10, Math.floor((width - 40 - groups.length * pairW) / Math.max(1, groups.length)));
  return (
    <>
      <svg viewBox={`0 0 ${width} ${chartH + 40}`} width="100%" role="img" aria-label="Fee collection status by term">
        {groups.map((g, i) => {
          const x = 40 + i * (pairW + gap);
          const chargedH = (g.charged / max) * chartH;
          const collectedH = (g.collected / max) * chartH;
          const rate = g.charged ? Math.round((1000 * g.collected) / g.charged) / 10 : null;
          return (
            <g key={g.label}>
              <rect x={x} y={chartH - chargedH} width={barW} height={chargedH} rx={3} className="chart-track-strong">
                <title>{`${g.label} charged: G$${formatNumber(g.charged)}`}</title>
              </rect>
              <rect
                x={x + barW + 4}
                y={chartH - collectedH}
                width={barW}
                height={collectedH}
                rx={3}
                className="chart-bar-accent"
              >
                <title>{`${g.label} collected: G$${formatNumber(g.collected)}`}</title>
              </rect>
              <text x={x + pairW / 2 - 2} y={chartH + 16} textAnchor="middle" className="chart-label-small">
                {g.label}
              </text>
              {rate !== null && (
                <text x={x + pairW / 2 - 2} y={chartH - Math.max(chargedH, collectedH) - 6} textAnchor="middle" className="chart-value-small">
                  {rate}%
                </text>
              )}
            </g>
          );
        })}
        <line x1={40} y1={chartH} x2={width - 10} y2={chartH} className="chart-axis" />
      </svg>
      <p className="chart-legend">
        <span className="chart-swatch chart-track-strong" /> Charged
        <span className="chart-swatch chart-bar-accent" /> Collected
      </p>
    </>
  );
}
