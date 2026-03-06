import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useBriefingHistory } from '../hooks/useBriefing'
import { useBriefingStore } from '../stores'

function getDaysInMonth(year: number, month: number) {
  return new Date(year, month + 1, 0).getDate()
}

function getFirstDayOfWeek(year: number, month: number) {
  return new Date(year, month, 1).getDay()
}

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

export default function BriefingCalendar() {
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth())
  const { briefings } = useBriefingHistory()
  const { setSelectedDate } = useBriefingStore()
  const navigate = useNavigate()

  const briefingDates = useMemo(() => {
    const dates = new Set<string>()
    for (const b of briefings) {
      dates.add(b.date)
    }
    return dates
  }, [briefings])

  const daysInMonth = getDaysInMonth(year, month)
  const firstDay = getFirstDayOfWeek(year, month)
  const todayStr = now.toISOString().slice(0, 10)

  const prevMonth = () => {
    if (month === 0) { setYear(year - 1); setMonth(11) }
    else setMonth(month - 1)
  }

  const nextMonth = () => {
    if (month === 11) { setYear(year + 1); setMonth(0) }
    else setMonth(month + 1)
  }

  const handleDayClick = (day: number) => {
    const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
    setSelectedDate(dateStr)
    navigate('/briefing')
  }

  const monthLabel = new Date(year, month).toLocaleDateString('zh-TW', { year: 'numeric', month: 'long' })

  return (
    <div className="p-4 sm:p-6 xl:p-8 space-y-6">
      <h1
        className="text-xl sm:text-2xl font-light"
        style={{ fontFamily: 'var(--bf-font-display)', color: 'var(--bf-text)' }}
      >
        簡報日曆
      </h1>

      {/* Month nav */}
      <div className="flex items-center justify-center gap-4">
        <button
          onClick={prevMonth}
          className="p-2"
          style={{ color: 'var(--bf-text-tertiary)' }}
        >
          <ChevronLeft size={18} />
        </button>
        <span className="text-sm" style={{ color: 'var(--bf-text)' }}>{monthLabel}</span>
        <button
          onClick={nextMonth}
          className="p-2"
          style={{ color: 'var(--bf-text-tertiary)' }}
        >
          <ChevronRight size={18} />
        </button>
      </div>

      {/* Calendar grid */}
      <div
        className="border"
        style={{ backgroundColor: 'var(--bf-bg-elevated)', borderColor: 'var(--bf-border)' }}
      >
        {/* Weekday headers */}
        <div className="grid grid-cols-7">
          {WEEKDAYS.map((d) => (
            <div
              key={d}
              className="text-center text-[10px] uppercase tracking-widest py-2 border-b"
              style={{ color: 'var(--bf-text-dim)', borderColor: 'var(--bf-border)' }}
            >
              {d}
            </div>
          ))}
        </div>

        {/* Days */}
        <div className="grid grid-cols-7">
          {Array.from({ length: firstDay }).map((_, i) => (
            <div key={`empty-${i}`} className="aspect-square" />
          ))}
          {Array.from({ length: daysInMonth }, (_, i) => i + 1).map((day) => {
            const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
            const hasBriefing = briefingDates.has(dateStr)
            const isToday = dateStr === todayStr

            return (
              <button
                key={day}
                onClick={() => handleDayClick(day)}
                className="aspect-square flex flex-col items-center justify-center gap-0.5 text-sm transition-colors"
                style={{
                  color: isToday ? 'var(--bf-accent)' : hasBriefing ? 'var(--bf-text)' : 'var(--bf-text-muted)',
                  fontWeight: isToday ? 600 : 400,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--bf-accent-alpha)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent'
                }}
              >
                {day}
                {hasBriefing && (
                  <span
                    className="w-1 h-1"
                    style={{ backgroundColor: 'var(--bf-accent)' }}
                  />
                )}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
