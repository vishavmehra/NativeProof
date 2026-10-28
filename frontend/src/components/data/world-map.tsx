"use client";

import { geoEqualEarth, geoPath } from "d3-geo";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import { useEffect, useMemo, useState } from "react";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";

import { MARKETS } from "@/components/forms/market-select";
import { cn } from "@/lib/utils";

// ISO 3166-1 alpha-2 → numeric for the shapes in world-atlas countries-110m (derived from its ids and names).
const ISO_NUMERIC =
  "FJ242 TZ834 CA124 KZ398 UZ860 PG598 ID360 AR032 CL152 SO706 KE404 SD729 TD148 HT332 RU643 BS044 NO578 GL304 TL626 ZA710 LS426 MX484 UY858 BR076 BO068 PE604 CO170 PA591 CR188 NI558 HN340 SV222 GT320 BZ084 VE862 GY328 SR740 FR250 EC218 PR630 JM388 CU192 ZW716 BW072 NA516 SN686 ML466 MR478 BJ204 NE562 NG566 CM120 TG768 GH288 CI384 GN324 GW624 LR430 SL694 BF854 GA266 ZM894 MW454 MZ508 SZ748 AO024 BI108 IL376 LB422 MG450 GM270 TN788 DZ012 JO400 AE784 QA634 KW414 IQ368 OM512 VU548 KH116 TH764 LA418 VN704 KP408 KR410 MN496 IN356 BD050 BT064 NP524 PK586 AF004 TJ762 KG417 TM795 IR364 SY760 AM051 SE752 BY112 UA804 PL616 AT040 HU348 MD498 RO642 LT440 LV428 EE233 DE276 BG100 GR300 AL008 HR191 CH756 LU442 BE056 NL528 PT620 ES724 IE372 NC540 NZ554 AU036 LK144 CN156 TW158 IT380 DK208 GB826 IS352 AZ031 GE268 PH608 MY458 BN096 SI705 FI246 SK703 CZ203 ER232 JP392 PY600 YE887 SA682 AQ010 CY196 MA504 EG818 LY434 ET231 DJ262 UG800 RW646 RS688 ME499 EH732 US840 CD180 DO214 FK238 TF260 CF140 CG178 GQ226 PS275 MM104 TR792 SB090 BA070 MK807 TT780 SS728";

const ALPHA2_BY_NUMERIC = new Map(ISO_NUMERIC.split(" ").map((e) => [e.slice(2), e.slice(0, 2)]));
const NAME_BY_CODE = new Map(MARKETS.map((m) => [m.country_code, m.display_name]));

export type MapDatum = { country_code: string; value: number };

type Countries = FeatureCollection<Geometry, { name: string }>;

const WIDTH = 960;
const HEIGHT = 470;

/**
 * World map that highlights markets by a real count (e.g. evidence records). Shading is relative to the largest
 * count shown; the textual list beside it is the exact data. Countries without data stay neutral.
 */
export function WorldMap({
  data,
  valueLabel,
  tone = "text-atlas",
  className,
}: {
  data: MapDatum[];
  /** Unit for the counts, e.g. "evidence records". */
  valueLabel: string;
  /** Text-color class for highlighted countries, e.g. "text-atlas" or "text-markets". */
  tone?: string;
  className?: string;
}) {
  const [countries, setCountries] = useState<Countries | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    import("world-atlas/countries-110m.json")
      .then((mod) => {
        const topo = (mod.default ?? mod) as unknown as Topology<{ countries: GeometryCollection<{ name: string }> }>;
        if (!cancelled) setCountries(feature(topo, topo.objects.countries) as Countries);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, []);

  const values = useMemo(() => new Map(data.filter((d) => d.value > 0).map((d) => [d.country_code.toUpperCase(), d.value])), [data]);
  const max = Math.max(1, ...values.values());
  const path = useMemo(() => geoPath(geoEqualEarth().fitExtent([[8, 8], [WIDTH - 8, HEIGHT - 8]], { type: "Sphere" })), []);
  const sorted = [...values.entries()].sort((a, b) => b[1] - a[1]);
  const summary = sorted.length
    ? `World map highlighting ${sorted.length} market${sorted.length > 1 ? "s" : ""}: ${sorted.map(([c, v]) => `${NAME_BY_CODE.get(c) ?? c} (${v} ${valueLabel})`).join(", ")}.`
    : "World map. No markets have been researched yet.";

  return (
    <figure className={cn("space-y-3", className)}>
      <div className="relative overflow-hidden rounded-xl border border-border bg-surface-muted">
        {countries ? (
          <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={summary} className="block h-auto w-full">
            <path d={path({ type: "Sphere" }) ?? undefined} className="fill-surface stroke-border" strokeWidth={1} />
            <g className={tone}>
              {countries.features.map((f: Feature<Geometry, { name: string }>, i) => {
                const code = ALPHA2_BY_NUMERIC.get(String(f.id ?? ""));
                const value = code ? values.get(code) : undefined;
                return (
                  <path
                    key={String(f.id ?? i)}
                    d={path(f) ?? undefined}
                    fill={value ? "currentColor" : "#e6e8ec"}
                    fillOpacity={value ? 0.35 + 0.65 * (value / max) : 1}
                    stroke="#ffffff"
                    strokeWidth={0.5}
                  >
                    {value && (
                      <title>
                        {NAME_BY_CODE.get(code!) ?? f.properties.name}: {value} {valueLabel}
                      </title>
                    )}
                  </path>
                );
              })}
            </g>
          </svg>
        ) : (
          <div className="flex aspect-[960/470] items-center justify-center text-xs text-ink-secondary">
            {failed ? "The map could not be loaded. The list below has the same data." : "Loading map…"}
          </div>
        )}
        {countries && sorted.length === 0 && (
          <p className="absolute inset-x-0 bottom-3 text-center text-xs text-ink-secondary">No markets researched yet.</p>
        )}
      </div>
      {sorted.length > 0 && (
        <figcaption>
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
            {sorted.map(([code, value]) => (
              <li key={code} className="flex items-center gap-1.5">
                <span aria-hidden className={cn("size-2.5 rounded-sm bg-current", tone)} style={{ opacity: 0.35 + 0.65 * (value / max) }} />
                <span className="text-ink">{NAME_BY_CODE.get(code) ?? code}</span>
                <span className="text-ink-secondary tabular-nums">
                  {value} {valueLabel}
                </span>
              </li>
            ))}
          </ul>
        </figcaption>
      )}
    </figure>
  );
}
