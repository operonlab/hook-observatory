import SendForm from '../components/SendForm'

export default function SendPage() {
  return (
    <div className="p-4 sm:p-6 md:p-8 max-w-2xl">
      <h1 className="mb-1 text-lg font-semibold" style={{ color: 'var(--text)' }}>
        發送通知
      </h1>
      <p className="mb-6 text-sm" style={{ color: 'var(--subtext1)' }}>
        手動發送推播通知至所有已註冊的裝置
      </p>
      <SendForm />
    </div>
  )
}
