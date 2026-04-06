import { useCallback, useState } from 'react'

interface Props {
  onUploaded?: () => void
}

export default function UploadDropzone({ onUploaded }: Props) {
  const [isDragging, setIsDragging] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback(() => {
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const files = Array.from(e.dataTransfer.files)
    setSelectedFiles((prev) => [...prev, ...files])
  }, [])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setSelectedFiles((prev) => [...prev, ...Array.from(e.target.files!)])
    }
  }, [])

  const removeFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index))
  }

  const handleUpload = async () => {
    // Upload logic will be wired in Phase 4 with actual ingestion pipeline
    // For now, just clear and notify
    setSelectedFiles([])
    onUploaded?.()
  }

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`rounded-lg border-2 border-dashed p-6 text-center transition ${
        isDragging ? 'border-blue-400 bg-blue-50' : 'border-gray-300 bg-gray-50'
      }`}
    >
      <div className="mb-3 text-3xl">📄</div>
      <p className="mb-2 text-sm text-gray-600">
        Drag & drop files here, or{' '}
        <label className="cursor-pointer text-blue-600 hover:underline">
          browse
          <input
            type="file"
            multiple
            accept=".pdf,.docx,.md,.html,.txt"
            onChange={handleFileSelect}
            className="hidden"
          />
        </label>
      </p>
      <p className="text-xs text-gray-400">
        Supported: PDF, DOCX, Markdown, HTML, TXT
      </p>

      {selectedFiles.length > 0 && (
        <div className="mt-4 space-y-2">
          {selectedFiles.map((file, i) => (
            <div
              key={`${file.name}-${i}`}
              className="flex items-center justify-between rounded bg-white px-3 py-2 text-sm"
            >
              <span className="truncate">{file.name}</span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">
                  {(file.size / 1024).toFixed(1)} KB
                </span>
                <button
                  onClick={() => removeFile(i)}
                  className="text-red-400 hover:text-red-600"
                >
                  ✕
                </button>
              </div>
            </div>
          ))}

          <button
            onClick={handleUpload}
            className="mt-2 w-full rounded-lg bg-blue-600 py-2 text-sm text-white hover:bg-blue-700"
          >
            Upload {selectedFiles.length} file{selectedFiles.length > 1 ? 's' : ''}
          </button>
        </div>
      )}
    </div>
  )
}
