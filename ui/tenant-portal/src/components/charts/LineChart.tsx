"use client";
import { LineChart as RechartsLineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';

import { useState, useEffect } from 'react';

interface ChartProps {
  data: any[];
  xKey: string;
  lines: { key: string; color: string; name?: string }[];
}

export function LineChart({ data, xKey, lines }: ChartProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  if (!mounted) return <div style={{ width: '100%', height: '300px' }} />;

  return (
    <div style={{ width: '100%', height: '300px' }}>
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <RechartsLineChart data={data} margin={{ top: 10, right: 20, bottom: 5, left: 0 }}>
          <defs>
            {lines.map((line, i) => (
              <linearGradient key={`grad-${line.key}`} id={`grad-${line.key}`} x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor={line.color} stopOpacity={1} />
                <stop offset="100%" stopColor={line.color} stopOpacity={0.6} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-light)" vertical={false} opacity={0.5} />
          <XAxis dataKey={xKey} stroke="var(--text-tertiary)" fontSize={12} tickLine={false} axisLine={false} dy={10} />
          <YAxis stroke="var(--text-tertiary)" fontSize={12} tickLine={false} axisLine={false} dx={-10} />
          <Tooltip
            contentStyle={{
              backgroundColor: 'var(--bg-surface)',
              backdropFilter: 'blur(12px)',
              border: '1px solid var(--border-light)',
              borderRadius: 'var(--radius-md)',
              boxShadow: 'var(--shadow-lg)'
            }}
            itemStyle={{ color: 'var(--text-primary)', fontWeight: 600 }}
            labelStyle={{ color: 'var(--text-tertiary)', marginBottom: '0.25rem' }}
          />
          <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '20px' }} />
          {lines.map((line, i) => (
            <Line
              key={line.key}
              type="monotone"
              dataKey={line.key}
              stroke={`url(#grad-${line.key})`}
              name={line.name || line.key}
              strokeWidth={3}
              dot={{ r: 4, fill: 'var(--bg-main)', strokeWidth: 2, stroke: line.color }}
              activeDot={{ r: 6, fill: line.color, strokeWidth: 0 }}
            />
          ))}
        </RechartsLineChart>
      </ResponsiveContainer>
    </div>
  );
}
