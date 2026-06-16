import React, { useMemo } from 'react';

export interface ShapWaterfallChartProps {
  shapValues: Record<string, number>;
  baseValue: number;
  finalScore: number;
  maxFeatures?: number;
}

interface ChartRow {
  feature: string;
  value: number;
  start: number;
  end: number;
  isPositive: boolean;
}

export function ShapWaterfallChart({
  shapValues,
  baseValue,
  finalScore,
  maxFeatures = 10,
}: ShapWaterfallChartProps) {
  const { rows, minX, maxX } = useMemo(() => {
    // 1. Sort features by absolute contribution
    const sortedFeatures = Object.entries(shapValues)
      .map(([feature, value]) => ({ feature, value, absValue: Math.abs(value) }))
      .sort((a, b) => b.absValue - a.absValue);

    // 2. Truncate to maxFeatures and calculate "Other" if necessary
    const topFeatures = sortedFeatures.slice(0, maxFeatures);

    // We calculate "Other" by seeing what's left to reach finalScore from the top features
    const topFeaturesSum = topFeatures.reduce((acc, curr) => acc + curr.value, 0);
    const otherValue = finalScore - (baseValue + topFeaturesSum);

    if (sortedFeatures.length > maxFeatures && Math.abs(otherValue) > 0.001) {
      topFeatures.push({ feature: 'Other Features', value: otherValue, absValue: Math.abs(otherValue) });
    }

    // 3. Compute cumulative positions
    let currentSum = baseValue;
    let localMin = baseValue;
    let localMax = baseValue;

    const computedRows: ChartRow[] = [];

    // Add the base value as a special starting bar (optional, but good for context)
    // We'll skip it in the waterfall but ensure min/max encapsulate it

    for (const item of topFeatures) {
      const start = currentSum;
      const end = currentSum + item.value;

      computedRows.push({
        feature: item.feature,
        value: item.value,
        start,
        end,
        isPositive: item.value >= 0,
      });

      currentSum = end;
      localMin = Math.min(localMin, start, end);
      localMax = Math.max(localMax, start, end);
    }

    // Add padding to min/max to ensure bars don't touch the absolute edges
    const range = localMax - localMin;
    const padding = range * 0.1 || 1; // 10% padding

    return {
      rows: computedRows,
      minX: localMin - padding,
      maxX: localMax + padding,
    };
  }, [shapValues, baseValue, finalScore, maxFeatures]);

  const range = maxX - minX;
  const getPercent = (val: number) => ((val - minX) / range) * 100;

  return (
    <div className="w-full text-sm font-sans">
      <div className="mb-2 flex justify-between text-gray-500 font-medium px-2">
        <span>Base Score: {baseValue.toFixed(3)}</span>
        <span>Final Score: {finalScore.toFixed(3)}</span>
      </div>

      <div className="relative border-l border-r border-gray-200 py-2">
        {/* Zero / Base Line */}
        <div
          className="absolute top-0 bottom-0 border-l-2 border-dashed border-[#e2e8f0] z-0"
          style={{ left: `${getPercent(baseValue)}%` }}
        />

        {/* Bars */}
        <div className="relative z-10 flex flex-col gap-3">
          {rows.map((row, i) => {
            const leftPercent = getPercent(Math.min(row.start, row.end));
            const widthPercent = Math.abs(getPercent(row.end) - getPercent(row.start));

            const colorClass = row.isPositive ? 'bg-[#1d4ed8]' : 'bg-[#dc2626]';
            const sign = row.isPositive ? '+' : '';
            const valueLabel = `${sign}${row.value.toFixed(3)} pts`;

            return (
              <div key={i} className="flex items-center px-2 group">
                {/* Feature Name */}
                <div className="w-1/3 truncate pr-4 text-right text-gray-700 font-medium" title={row.feature}>
                  {row.feature}
                </div>

                {/* Chart Area */}
                <div className="w-2/3 relative h-6">
                  {/* The Bar */}
                  <div
                    className={`absolute h-full rounded-sm opacity-90 transition-opacity group-hover:opacity-100 ${colorClass}`}
                    style={{
                      left: `${leftPercent}%`,
                      width: `${Math.max(widthPercent, 0.5)}%`, // min-width for very small values
                    }}
                    role="progressbar"
                    aria-label={`${row.feature}: ${valueLabel}`}
                    aria-valuenow={row.value}
                  />

                  {/* Label */}
                  <div
                    className="absolute top-1/2 -translate-y-1/2 text-xs font-semibold whitespace-nowrap px-2"
                    style={{
                      left: row.isPositive ? `${leftPercent + widthPercent}%` : 'auto',
                      right: !row.isPositive ? `${100 - leftPercent}%` : 'auto',
                      color: row.isPositive ? '#1d4ed8' : '#dc2626',
                    }}
                  >
                    {valueLabel}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
