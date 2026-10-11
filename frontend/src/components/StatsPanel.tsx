import type { CategoricalStats, ContinuousStats, SeriesClassStats, SeriesStats, Stats } from "../types";
import { formatArea, formatValue } from "../format";

interface Props {
  stats: Stats | null;
  valueLabel: string;
  isRgb: boolean;
}

export function StatsPanel({ stats, valueLabel, isRgb }: Props) {
  if (!stats) {
    return (
      <section className="card">
        <h3 className="card-title">Statistics</h3>
        <p className="muted">
          {isRgb
            ? "Colour composites combine three bands, so there is no single value to summarise."
            : "Statistics could not be computed for this map."}
        </p>
      </section>
    );
  }
  if (stats.kind === "series") return <SeriesValueStats stats={stats} valueLabel={valueLabel} />;
  if (stats.kind === "series_categorical") return <SeriesClassShares stats={stats} />;
  return stats.kind === "categorical" ? (
    <ClassStats stats={stats} />
  ) : (
    <ValueStats stats={stats} valueLabel={valueLabel} />
  );
}

/** Multi-map figure: the regional mean of every map as a bar, with its range beside it. */
function SeriesValueStats({ stats, valueLabel }: { stats: SeriesStats; valueLabel: string }) {
  const means = stats.rows.map((r) => r.mean).filter((v): v is number => v !== null);
  // Bars start at zero unless the values go below it (temperatures, indices).
  const low = Math.min(0, ...means);
  const span = Math.max(...means, 0) - low || 1;
  const gaps = stats.rows.some((r) => r.coverage_percent !== null && r.coverage_percent < 99.5);
  return (
    <section className="card">
      <div className="card-head">
        <h3 className="card-title">Statistics by map</h3>
        <span className="card-sub">{valueLabel}</span>
      </div>
      <div className="table-scroll">
        <table className="series-table">
          <thead>
            <tr>
              <th scope="col">Map</th>
              <th scope="col" className="series-mean-head">
                Mean
              </th>
              <th scope="col">Min</th>
              <th scope="col">Max</th>
              <th scope="col">Std dev</th>
              {gaps && <th scope="col">Data</th>}
            </tr>
          </thead>
          <tbody>
            {stats.rows.map((r) => (
              <tr key={r.label}>
                <th scope="row">{r.label}</th>
                <td className="series-mean">
                  <span className="series-track" aria-hidden="true">
                    {r.mean !== null && (
                      <span
                        className="series-fill"
                        style={{
                          left: `${((Math.min(r.mean, 0) - low) / span) * 100}%`,
                          width: `${Math.max((Math.abs(r.mean) / span) * 100, 0.5)}%`,
                        }}
                      />
                    )}
                  </span>
                  <span>{formatValue(r.mean)}</span>
                </td>
                <td>{formatValue(r.min)}</td>
                <td>{formatValue(r.max)}</td>
                <td>{formatValue(r.std)}</td>
                {gaps && <td>{r.coverage_percent === null ? "–" : `${Math.round(r.coverage_percent)}%`}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="kv">
        <div>
          <dt>Region area</dt>
          <dd>{formatArea(stats.area_km2)}</dd>
        </div>
      </dl>
    </section>
  );
}

/** Multi-map figure of a classified band: each class's share of the area, map by map. */
function SeriesClassShares({ stats }: { stats: SeriesClassStats }) {
  const share = (p: number) => (p >= 0.05 ? p.toFixed(1) : p > 0 ? "<0.1" : "–");
  return (
    <section className="card">
      <div className="card-head">
        <h3 className="card-title">Class shares by map</h3>
        <span className="card-sub">% of area · region {formatArea(stats.area_km2)}</span>
      </div>
      <div className="table-scroll">
        <table className="series-table">
          <thead>
            <tr>
              <th scope="col">Class</th>
              {stats.panels.map((label) => (
                <th scope="col" key={label}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {stats.rows.map((r) => (
              <tr key={r.value}>
                <th scope="row">
                  {r.color && <span className="class-swatch" style={{ background: r.color }} aria-hidden="true" />}
                  {r.class}
                </th>
                {r.percent.map((p, i) => (
                  <td key={i}>{share(p)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ValueStats({ stats, valueLabel }: { stats: ContinuousStats; valueLabel: string }) {
  const get = (name: string) => stats.rows.find((r) => r.name === name)?.value;
  const headline = [
    { label: "Mean", value: get("Mean") },
    { label: "Median", value: get("Median") },
    { label: "Minimum", value: get("Minimum") },
    { label: "Maximum", value: get("Maximum") },
  ];
  const secondary = [
    { label: "Standard deviation", value: formatValue(get("Standard deviation")) },
    { label: "10th percentile", value: formatValue(get("10th percentile")) },
    { label: "90th percentile", value: formatValue(get("90th percentile")) },
    { label: "Region area", value: formatArea(stats.area_km2) },
  ];
  if (stats.coverage_percent !== null && stats.coverage_percent !== undefined) {
    secondary.push({ label: "Region with data", value: `${Math.round(stats.coverage_percent)}%` });
  }

  return (
    <section className="card">
      <div className="card-head">
        <h3 className="card-title">Statistics</h3>
        <span className="card-sub">{valueLabel}</span>
      </div>

      <div className="stat-tiles">
        {headline.map((s) => (
          <div className="stat-tile" key={s.label}>
            <div className="stat-label">{s.label}</div>
            <div className="stat-value">{formatValue(s.value)}</div>
          </div>
        ))}
      </div>

      {stats.histogram.length > 0 && <Histogram bins={stats.histogram} label={valueLabel} />}

      <dl className="kv">
        {secondary.map((s) => (
          <div key={s.label}>
            <dt>{s.label}</dt>
            <dd>{s.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function Histogram({ bins, label }: { bins: ContinuousStats["histogram"]; label: string }) {
  const max = Math.max(...bins.map((b) => b.pixels), 1);
  const first = bins[0];
  const last = bins[bins.length - 1];
  return (
    <figure className="histogram">
      <div className="histogram-bars" role="img" aria-label={`Distribution of ${label} across the region`}>
        {bins.map((b, i) => (
          <div
            key={i}
            className="histogram-bar"
            style={{ height: `${Math.max((b.pixels / max) * 100, b.pixels > 0 ? 2 : 0)}%` }}
            title={`${formatValue(b.from)} to ${formatValue(b.to)}`}
          />
        ))}
      </div>
      <figcaption>
        <span>{formatValue(first.from)}</span>
        <span className="histogram-caption">Distribution across the region</span>
        <span>{formatValue(last.to)}</span>
      </figcaption>
    </figure>
  );
}

function ClassStats({ stats }: { stats: CategoricalStats }) {
  const max = Math.max(...stats.rows.map((r) => r.percent), 1);
  return (
    <section className="card">
      <div className="card-head">
        <h3 className="card-title">Class areas</h3>
        <span className="card-sub">Region {formatArea(stats.area_km2)}</span>
      </div>
      <ul className="class-bars">
        {stats.rows.map((r) => (
          <li key={r.value}>
            <div className="class-row">
              <span className="class-name">
                {r.color && <span className="class-swatch" style={{ background: r.color }} aria-hidden="true" />}
                {r.class}
              </span>
              <span className="class-figures">
                <span className="class-area">{formatArea(r.area_km2)}</span>
                <span className="class-percent">{r.percent >= 0.05 ? `${r.percent.toFixed(1)}%` : "<0.1%"}</span>
              </span>
            </div>
            <div className="class-track">
              <div
                className="class-fill"
                style={{ width: `${Math.max((r.percent / max) * 100, 0.5)}%`, background: r.color }}
              />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
