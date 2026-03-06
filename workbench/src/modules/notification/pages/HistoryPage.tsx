import HistoryTable from '../components/HistoryTable'

export default function HistoryPage() {
  return (
    <div className="p-4 sm:p-6 md:p-8">
      <h1 className="mb-1 text-lg font-semibold" style={{ color: 'var(--text)' }}>
        通知記錄
      </h1>
      <p className="mb-6 text-sm" style={{ color: 'var(--subtext1)' }}>
        所有已發送推播的歷史紀錄
      </p>
      <HistoryTable />
    </div>
  )
}
