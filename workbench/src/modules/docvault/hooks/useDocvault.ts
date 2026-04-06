import { useDocvaultStore } from '../stores'
import {
  useDashboardQuery,
  useDocumentsQuery,
  useQAMutation,
  useSearchQuery,
} from './queries'

/**
 * Composite hook combining store state with TanStack queries.
 */
export function useDocvault() {
  const store = useDocvaultStore()

  const dashboard = useDashboardQuery()
  const documents = useDocumentsQuery({
    page: store.documentsPage,
    tags: store.activeTag,
    status: store.activeStatus,
  })
  const search = useSearchQuery(store.searchQuery)
  const qaMutation = useQAMutation()

  return {
    // Store state
    ...store,

    // Queries
    dashboard,
    documents,
    search,

    // QA
    qaMutation,
    askQuestion: (question: string) => {
      store.setQAQuestion(question)
      return qaMutation.mutateAsync({
        question,
        mode: store.qaMode,
        domain: store.qaDomain,
      })
    },
  }
}
