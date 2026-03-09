import { ImagePlus, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { uploadIcon } from '../api'

interface IconUploadProps {
  value: string | null
  onChange: (url: string | null) => void
  size?: 'sm' | 'md'
}

export default function IconUpload({ value, onChange, size = 'md' }: IconUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  const dim = size === 'sm' ? 'w-8 h-8' : 'w-10 h-10'
  const iconSize = size === 'sm' ? 14 : 16
  const xSize = size === 'sm' ? 10 : 12

  const handleFile = async (file: File) => {
    if (!file.type.startsWith('image/')) return
    setUploading(true)
    try {
      const url = await uploadIcon(file)
      onChange(url)
    } catch {
      // silently fail
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) handleFile(f)
          e.target.value = ''
        }}
      />

      {value ? (
        <div className="relative shrink-0">
          <img
            src={`/api${value}`}
            alt="icon"
            className={`${dim} rounded-lg object-cover`}
            style={{ border: '1px solid var(--fn-border)' }}
          />
          <button
            type="button"
            onClick={() => onChange(null)}
            className="absolute -top-1.5 -right-1.5 rounded-full p-0.5"
            style={{ backgroundColor: 'var(--fn-bg-elevated)', color: 'var(--fn-text-muted)' }}
          >
            <X size={xSize} />
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className={`flex items-center justify-center ${dim} rounded-lg shrink-0`}
          style={{
            border: '1px dashed var(--fn-border)',
            color: 'var(--fn-text-muted)',
            backgroundColor: 'var(--fn-bg-surface)',
          }}
        >
          {uploading ? (
            <div
              className="h-4 w-4 animate-spin rounded-full border-2 border-t-transparent"
              style={{ borderColor: 'var(--fn-accent)', borderTopColor: 'transparent' }}
            />
          ) : (
            <ImagePlus size={iconSize} />
          )}
        </button>
      )}

      {size === 'md' && (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className="text-[11px]"
          style={{ color: 'var(--fn-accent)' }}
        >
          {value ? '更換圖示' : '上傳圖示'}
        </button>
      )}
    </div>
  )
}
