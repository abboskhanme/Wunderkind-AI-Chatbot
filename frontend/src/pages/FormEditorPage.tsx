import type { ComponentType } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { ArrowLeft, ClipboardList, Inbox, ListChecks, Settings2 } from 'lucide-react'
import { formsApi } from '@/api/forms'
import type { FormOut } from '@/api/types'
import { Badge, Button, Card, Empty, Loading } from '@/components/ui'
import { ErrorState } from '@/pages/funnel/shared'
import { fmtAgo, fmtNumber } from '@/lib/format'
import { cn } from '@/lib/cn'
import {
  LinkRow, formKey, settingsPatch, toQuestionsDraft, toQuestionsPayload, toSettingsDraft, useDraft,
  useUnsavedGuard,
} from './forms/shared'
import { QuestionsTab } from './forms/QuestionsTab'
import { ResponsesTab } from './forms/ResponsesTab'
import { FormSettingsTab } from './forms/FormSettingsTab'

type TabId = 'questions' | 'answers' | 'settings'

const TABS: { id: TabId; label: string; icon: ComponentType<{ className?: string }> }[] = [
  { id: 'questions', label: 'Savollar', icon: ListChecks },
  { id: 'answers', label: 'Javoblar', icon: Inbox },
  { id: 'settings', label: 'Sozlamalar', icon: Settings2 },
]

function BackLink() {
  return (
    <Link to="/forms" className="mb-3 inline-flex items-center gap-1 text-sm font-medium text-gray-500 hover:text-gray-800">
      <ArrowLeft className="h-4 w-4" /> Formalar
    </Link>
  )
}

/** Both drafts live here so switching tabs never loses unsaved edits. */
function FormEditor({ form }: { form: FormOut }) {
  const [params, setParams] = useSearchParams()
  const active: TabId = TABS.find((t) => t.id === params.get('tab'))?.id ?? 'questions'

  const questionsBase = toQuestionsDraft(form)
  const [questions, setQuestions, resetQuestions] = useDraft(questionsBase)
  const questionsDirty = JSON.stringify(toQuestionsPayload(questions)) !== JSON.stringify(toQuestionsPayload(questionsBase))

  const settingsBase = toSettingsDraft(form)
  const [settings, setSettings, resetSettings] = useDraft(settingsBase)
  const settingsDirty = Object.keys(settingsPatch(settings, settingsBase)).length > 0

  useUnsavedGuard(questionsDirty || settingsDirty)

  function selectTab(id: TabId) {
    setParams(id === 'questions' ? {} : { tab: id }, { replace: true })
  }

  const dirtyTab: Record<TabId, boolean> = { questions: questionsDirty, answers: false, settings: settingsDirty }

  return (
    <>
      <BackLink />
      <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="min-w-0 break-words text-xl font-semibold text-gray-900">{form.title}</h1>
            {form.is_active
              ? <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-200">Faol</Badge>
              : <Badge>Nofaol</Badge>}
          </div>
          <p className="mt-1 text-sm text-gray-500">
            {form.submissions > 0
              ? `${fmtNumber(form.submissions)} ta javob · oxirgisi ${fmtAgo(form.last_submission_at)}`
              : "Hali javob yo'q"}
          </p>
        </div>
        <LinkRow url={form.url} className="w-full lg:w-96" />
      </div>

      <div className="mb-6 overflow-x-auto border-b border-gray-200">
        <nav className="-mb-px flex gap-1" aria-label="Forma bo'limlari">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => selectTab(id)}
              className={cn(
                'flex shrink-0 items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors',
                id === active
                  ? 'border-brand-600 text-brand-700'
                  : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-800',
              )}
              aria-current={id === active ? 'page' : undefined}
            >
              <Icon className="h-4 w-4" />
              {label}
              {id === 'answers' && form.submissions > 0 && (
                <span className="rounded-full bg-gray-100 px-1.5 text-xs tabular-nums text-gray-600">{fmtNumber(form.submissions)}</span>
              )}
              {dirtyTab[id] && <span className="h-1.5 w-1.5 rounded-full bg-amber-500" title="Saqlanmagan o'zgarishlar" />}
            </button>
          ))}
        </nav>
      </div>

      {active === 'questions' && (
        <QuestionsTab form={form} draft={questions} setDraft={setQuestions} dirty={questionsDirty} reset={resetQuestions} />
      )}
      {active === 'answers' && <ResponsesTab form={form} />}
      {active === 'settings' && (
        <FormSettingsTab form={form} draft={settings} setDraft={setSettings} dirty={settingsDirty} reset={resetSettings} />
      )}
    </>
  )
}

export default function FormEditorPage() {
  const { formId = '' } = useParams()
  const navigate = useNavigate()
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: formKey(formId),
    queryFn: () => formsApi.get(formId),
    enabled: Boolean(formId),
  })

  if (isLoading) return <Loading />
  if (!data) {
    const notFound = axios.isAxiosError(error) && error.response?.status === 404
    return (
      <>
        <BackLink />
        <Card>
          {notFound || !isError ? (
            <Empty
              icon={<ClipboardList className="h-6 w-6" />}
              title="Forma topilmadi"
              text="U o'chirilgan bo'lishi mumkin."
              action={<Button variant="secondary" onClick={() => navigate('/forms')}>Formalar ro'yxati</Button>}
            />
          ) : (
            <ErrorState error={error} onRetry={() => refetch()} />
          )}
        </Card>
      </>
    )
  }
  // Keyed: another form never inherits this one's drafts
  return <FormEditor key={data.id} form={data} />
}
