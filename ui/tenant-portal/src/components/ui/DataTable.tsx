import React from 'react';

export interface Column<T> {
  key: string;
  header: string;
  render?: (item: T) => React.ReactNode;
}

interface DataTableProps<T> {
  data: T[];
  columns: Column<T>[];
  keyExtractor: (item: T) => string;
}

export function DataTable<T>({ data, columns, keyExtractor }: DataTableProps<T>) {
  return (
    <div style={{
      width: '100%',
      overflowX: 'auto',
      borderRadius: 'var(--radius-md)',
      border: '1px solid var(--border-light)',
      backgroundColor: 'rgba(0,0,0,0.2)'
    }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.875rem' }}>
        <thead style={{
          backgroundColor: 'rgba(255,255,255,0.03)',
          borderBottom: '1px solid var(--border-light)'
        }}>
          <tr>
            {columns.map(col => (
              <th key={col.key} style={{
                padding: '1rem',
                color: 'var(--text-secondary)',
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                fontSize: '0.75rem'
              }}>
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((item, index) => (
            <tr
              key={keyExtractor(item)}
              style={{
                borderBottom: index === data.length - 1 ? 'none' : '1px solid rgba(255,255,255,0.05)',
                transition: 'background-color 0.2s',
                backgroundColor: 'transparent'
              }}
              onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--bg-subtle)'}
              onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
            >
              {columns.map(col => (
                <td key={col.key} style={{ padding: '1rem', color: 'var(--text-primary)' }}>
                  {col.render ? col.render(item) : String((item as any)[col.key])}
                </td>
              ))}
            </tr>
          ))}
          {data.length === 0 && (
            <tr>
              <td colSpan={columns.length} style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-tertiary)' }}>
                No data available.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
