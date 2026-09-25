import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { BookOpen, Save } from 'lucide-react'
import { settingsApi } from '@/api/settings'
import { errorMessage } from '@/api/client'
import { Button, Card, Empty, Label, Loading, PageHeader, Textarea } from '@/components/ui'
import { changedValues, initialDraft, mergeDraft, type Draft } from '@/components/SettingField'

export default function KnowledgePage() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['settings'], queryFn: settingsApi.get })
  const items = useMemo(() => data?.groups.find((g) => g.id === 'knowledge')?.items ?? [], [data])
  const [draft, setDraft] = useState<Draft>({})
  const prevItems = useRef<typeof items>([])

  // Adopt server values only for fields the user has not edited (a refetch must
  // never wipe a half-written knowledge base).
  useEffect(() => {
    const before = prevItems.current
    setDraft((d) => (before.length ? mergeDraft(before, items, d) : initialDraft(items)))
    prevItems.current = items
  }, [items])
  const changes = changedValues(items, draft)
  const dirty = Object.keys(changes).length > 0

  useEffect(() => {
    if (!dirty) return
    const handler = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  const save = useMutation({
    mutationFn: () => settingsApi.update(changes),
    onSuccess: (res) => {
      const fresh = res.groups.find((g) => g.id === 'knowledge')
      if (fresh) setDraft(initialDraft(fresh.items))
      qc.setQueryData(['settings'], res)
      toast.success('Bilim bazasi saqlandi — agent darhol yangi ma\'lumot bilan javob beradi')
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const saveButton = (
    <Button icon={<Save className="h-4 w-4" />} disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
      Saqlash
    </Button>
  )

  return (
    <>
      <PageHeader
        title="Bilim bazasi"
        subtitle="AI agent faqat shu yerdagi ma'lumotlar asosida javob beradi. Yo'q narsani o'ylab topmaydi — operatorga o'tkazadi."
        action={saveButton}
      />
      {isLoading && <Loading />}
      {data && items.length === 0 && <Empty icon={<BookOpen className="h-6 w-6" />} title="Bilim bazasi bo'limlari topilmadi" />}
      <div className="space-y-4">
        {items.map((item) => {
          const value = draft[item.key] ?? ''
          return (
            <Card key={item.key} className="p-5">
              <Label hint={`${value.length} belgi`}>{item.label}</Label>
              {item.help && <p className="mb-2 text-xs text-gray-500">{item.help}</p>}
              <Textarea
                rows={item.key === 'KB_COURSES' || item.key === 'KB_FAQ' ? 12 : 7}
                value={value}
                placeholder={item.placeholder}
                onChange={(e) => setDraft((d) => ({ ...d, [item.key]: e.target.value }))}
                className="font-mono text-[13px]"
              />
            </Card>
          )
        })}
      </div>
      {items.length > 0 && (
        <div className="sticky bottom-0 mt-6 flex items-center justify-end gap-3 border-t border-gray-200 bg-gray-50/90 py-3 backdrop-blur">
          {dirty && <span className="text-xs text-amber-600">Saqlanmagan o'zgarishlar bor</span>}
          {saveButton}
        </div>
      )}
    </>
  )
}
