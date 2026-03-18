import { useState } from 'react'
import type { CatalogListResponse, CatalogSkill } from '../types'
import { DOMAIN_COLORS } from '../types'

interface SkillListViewProps {
  data: CatalogListResponse | null
  searchQuery: string
  onSkillClick: (name: string) => void
  selectedSkillName?: string | null
  onDomainFilter: (domain: string | null) => void
  activeDomain: string | null
}

type SortKey = 'name' | 'domain' | 'health_score' | 'version' | 'tools' | 'body_lines'
type SortDir = 'asc' | 'desc'

export default function SkillListView({
  data,
  onSkillClick,
  selectedSkillName,
  onDomainFilter,
  activeDomain,
}: SkillListViewProps) {
  const [sortKey, setSortKey] = useState<SortKey>('name')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const sorted = [...(data?.items ?? [])].sort((a, b) => {
    let cmp = 0
    switch (sortKey) {
      case 'name':
        cmp = a.name.localeCompare(b.name)
        break
      case 'domain':
        cmp = a.domain.localeCompare(b.domain)
        break
      case 'health_score':
        cmp = (a.health_score ?? -1) - (b.health_score ?? -1)
        break
      case 'version':
        cmp = (a.version ?? '').localeCompare(b.version ?? '')
        break
      case 'tools':
        cmp = a.tools.length - b.tools.length
        break
      case 'body_lines':
        cmp = a.body_lines - b.body_lines
        break
    }
    return sortDir === 'asc' ? cmp : -cmp
  })

  const domainEntries = Object.entries(data?.domain_counts ?? {}).sort((a, b) => b[1] - a[1])

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Domain Filter Pills */}
      {domainEntries.length > 0 && (
        <div
          className="flex items-center gap-2 px-4 py-2 border-b overflow-x-auto shrink-0"
          style={{ borderColor: 'var(--av-border)' }}
        >
          <button
            type="button"
            onClick={() => onDomainFilter(null)}
            className="shrink-0 text-xs px-3 py-1 rounded-full border transition-colors"
            style={{
              borderColor: activeDomain === null ? 'var(--av-accent)' : 'var(--av-border)',
              backgroundColor: activeDomain === null ? 'var(--av-accent-alpha)' : 'transparent',
              color: activeDomain === null ? 'var(--av-accent)' : 'var(--av-text-muted)',
            }}
          >
            全部
          </button>
          {domainEntries.map(([domain, count]) => {
            const color = DOMAIN_COLORS[domain] ?? '#888'
            const active = activeDomain === domain
            return (
              <button
                key={domain}
                type="button"
                onClick={() => onDomainFilter(active ? null : domain)}
                className="shrink-0 flex items-center gap-1.5 text-xs px-3 py-1 rounded-full border transition-colors"
                style={{
                  borderColor: active ? color : 'var(--av-border)',
                  backgroundColor: active ? `${color}26` : 'transparent',
                  color: active ? color : 'var(--av-text-muted)',
                }}
              >
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: color }}
                />
                {domain}
                <span style={{ opacity: 0.7 }}>{count}</span>
              </button>
            )
          })}
        </div>
      )}

      {/* Table */}
      <div className="flex-1 overflow-auto">
        {!data ? (
          <div className="p-6" style={{ color: 'var(--av-text-muted)' }}>
            載入中...
          </div>
        ) : sorted.length === 0 ? (
          <div className="p-6" style={{ color: 'var(--av-text-muted)' }}>
            無符合條件的技能
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="sticky top-0" style={{ backgroundColor: 'var(--av-bg-surface)' }}>
              <tr
                className="text-left border-b"
                style={{ borderColor: 'var(--av-border)', color: 'var(--av-text-muted)' }}
              >
                <SortTh
                  label="Name"
                  sortKey="name"
                  active={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                />
                <SortTh
                  label="Domain"
                  sortKey="domain"
                  active={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                />
                <SortTh
                  label="Health"
                  sortKey="health_score"
                  active={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                />
                <SortTh
                  label="Version"
                  sortKey="version"
                  active={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                  hideOnMobile
                />
                <SortTh
                  label="Tools"
                  sortKey="tools"
                  active={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                  hideOnMobile
                />
                <th className="pb-2 pr-4 font-medium hidden md:table-cell">Tags</th>
                <SortTh
                  label="Lines"
                  sortKey="body_lines"
                  active={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                  hideOnMobile
                />
              </tr>
            </thead>
            <tbody>
              {sorted.map((skill) => (
                <SkillRow
                  key={skill.name}
                  skill={skill}
                  selected={skill.name === selectedSkillName}
                  onClick={() => onSkillClick(skill.name)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Footer count */}
      {data && data.total > data.items.length && (
        <div
          className="px-4 py-2 text-xs border-t shrink-0"
          style={{ color: 'var(--av-text-muted)', borderColor: 'var(--av-border)' }}
        >
          顯示 {data.items.length} / {data.total} 筆
        </div>
      )}
    </div>
  )
}

// ── SortTh ─────────────────────────────────────────────────────────────────

function SortTh({
  label,
  sortKey,
  active,
  dir,
  onSort,
  hideOnMobile,
}: {
  label: string
  sortKey: SortKey
  active: SortKey
  dir: SortDir
  onSort: (k: SortKey) => void
  hideOnMobile?: boolean
}) {
  const isActive = active === sortKey
  return (
    <th
      className={`pb-2 pr-4 font-medium cursor-pointer select-none${hideOnMobile ? ' hidden md:table-cell' : ''}`}
      onClick={() => onSort(sortKey)}
    >
      <span className="flex items-center gap-1">
        {label}
        <span style={{ opacity: isActive ? 1 : 0.3, fontSize: 10 }}>
          {isActive ? (dir === 'asc' ? '↑' : '↓') : '↕'}
        </span>
      </span>
    </th>
  )
}

// ── SkillRow ────────────────────────────────────────────────────────────────

function SkillRow({
  skill,
  selected,
  onClick,
}: {
  skill: CatalogSkill
  selected: boolean
  onClick: () => void
}) {
  const domainColor = DOMAIN_COLORS[skill.domain] ?? '#888'
  const health = skill.health_score ?? 0
  const healthColor =
    health >= 70 ? 'var(--av-pass)' : health >= 40 ? 'var(--av-warn)' : 'var(--av-fail)'

  return (
    <tr
      className="border-b cursor-pointer transition-colors"
      style={{
        borderColor: 'var(--av-border)',
        backgroundColor: selected ? 'var(--av-accent-alpha)' : undefined,
      }}
      onClick={onClick}
      onMouseEnter={(e) => {
        if (!selected)
          (e.currentTarget as HTMLTableRowElement).style.backgroundColor = 'rgba(250,179,135,0.05)'
      }}
      onMouseLeave={(e) => {
        if (!selected) (e.currentTarget as HTMLTableRowElement).style.backgroundColor = ''
      }}
    >
      {/* Name */}
      <td className="py-3 pr-4">
        <span
          className="font-mono text-xs"
          style={{ color: selected ? 'var(--av-accent)' : 'var(--av-text)' }}
        >
          {skill.name}
        </span>
      </td>

      {/* Domain */}
      <td className="py-3 pr-4">
        <span
          className="inline-block text-xs px-2 py-0.5 rounded-full whitespace-nowrap"
          style={{
            backgroundColor: `${domainColor}26`,
            color: domainColor,
          }}
        >
          {skill.domain}
        </span>
      </td>

      {/* Health */}
      <td className="py-3 pr-4">
        <div className="flex items-center gap-1.5">
          <div
            className="rounded-full overflow-hidden"
            style={{ width: 40, height: 6, backgroundColor: 'var(--av-border)' }}
          >
            <div
              className="h-full rounded-full"
              style={{
                width: `${health}%`,
                backgroundColor: healthColor,
              }}
            />
          </div>
          <span className="text-xs" style={{ color: healthColor }}>
            {skill.health_score !== null ? health : '—'}
          </span>
        </div>
      </td>

      {/* Version */}
      <td className="py-3 pr-4 hidden md:table-cell">
        <span className="text-xs" style={{ color: 'var(--av-text-muted)' }}>
          {skill.version ?? '—'}
        </span>
      </td>

      {/* Tools count */}
      <td className="py-3 pr-4 hidden md:table-cell">
        <span className="text-xs" style={{ color: 'var(--av-text-secondary)' }}>
          {skill.tools.length}
        </span>
      </td>

      {/* Tags (truncated) */}
      <td className="py-3 pr-4 hidden md:table-cell" style={{ maxWidth: 160 }}>
        <div className="flex flex-wrap gap-1">
          {skill.tags.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="text-[10px] px-1.5 py-0.5 rounded"
              style={{
                backgroundColor: 'var(--av-bg)',
                color: 'var(--av-text-muted)',
                border: '1px solid var(--av-border)',
              }}
            >
              {tag}
            </span>
          ))}
          {skill.tags.length > 3 && (
            <span className="text-[10px]" style={{ color: 'var(--av-text-muted)' }}>
              +{skill.tags.length - 3}
            </span>
          )}
        </div>
      </td>

      {/* Lines */}
      <td className="py-3 hidden md:table-cell">
        <span className="text-xs" style={{ color: 'var(--av-text-muted)' }}>
          {skill.body_lines}
        </span>
      </td>
    </tr>
  )
}
