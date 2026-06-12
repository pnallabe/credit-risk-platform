"use client";
import { BarChart as RechartsBarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Cell } from 'recharts';

import { useState, useEffect } from 'react';

interface ChartProps {
  data: any[];
  xKey: string;
  bars: { key: string; color: string; name?: string; stackId?: string }[];
}

export function BarChart({ data, xKey, bars }: ChartProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  if (!mounted) return <div style={{ width: '100%', height: '300px' }} />;

  return (
    <div style={{ width: '100%', height: '300px' }}>
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <RechartsBarChart data={data} margin={{ top: 10, right: 20, bottom: 5, left: 0 }}>
          <defs>
            {bars.map((bar) => (
              <linearGradient key={`bar-grad-${bar.key}`} id={`bar-grad-${bar.key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={bar.color} stopOpacity={0.9} />
                <stop offset="100%" stopColor={bar.color} stopOpacity={0.3} />
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
            cursor={{ fill: 'var(--bg-subtle)' }}
          />
          <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '20px' }} />
          {bars.map((bar) => (
            <Bar
              key={bar.key}
              dataKey={bar.key}
              name={bar.name || bar.key}
              stackId={bar.stackId}
              radius={bar.stackId ? [0, 0, 0, 0] : [4, 4, 0, 0]}
            >
              {data.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={`url(#bar-grad-${bar.key})`} />
              ))}
            </Bar>
          ))}
        </RechartsBarChart>
      </ResponsiveContainer>
    </div>
  );
}
