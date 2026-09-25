import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { ArrowDown, ArrowUp, Bot, ImagePlus, Pencil, Plus, Save, Trash2, X } from 'lucide-react'
import { botMenuApi } from '@/api/botMenu'
import { errorMessage } from '@/api/client'
import type { MenuItem, MenuItemInput } from '@/api/types'
import { Badge, Button, Card, CardHeader, Empty, Input, Label, Loading, Modal, PageHeader, Textarea, Toggle } from '@/components/ui'
import { AuthImage } from '@/components/AuthImage'

const COMMAND_RE = /^[a-z0-9_]{1,32}$/
const MAX_IMAGES = 10

function ItemModal({ item, open, onClose }: { item: MenuItem | null; open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState<MenuItemInput>({ command: '', title: '', text: '', is_active: true })
  useEffect(() => {
    if (open) setForm(item ? { command: item.command, title: item.title, text: item.text ?? '', is_active: item.is_active } : { command: '', title: '', text: '', is_active: true })
  }, [open, item])

  const save = useMutation({
    mutationFn: () => (item ? botMenuApi.update(item.id, form) : botMenuApi.create(form)),
    onSuccess: () => {
      toast.success('Saqlandi')
      qc.invalidateQueries({ queryKey: ['bot-menu'] })
      onClose()
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const commandOk = COMMAND_RE.test(form.command) && !['start', 'menu'].includes(form.command)
  const valid = commandOk && form.title.trim().length > 0

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={item ? "Bo'limni tahrirlash" : "Yangi bo'lim"}
      wide
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Bekor qilish</Button>
          <Button icon={<Save className="h-4 w-4" />} disabled={!valid} loading={save.isPending} onClick={() => save.mutate()}>Saqlash</Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label>Tugma matni</Label>
            <Input value={form.title} maxLength={64} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="💰 Kurslar narxi" />
          </div>
          <div>
            <Label hint="a-z, 0-9, _">Buyruq</Label>
            <div className="relative">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-gray-400">/</span>
              <Input value={form.command} maxLength={32} onChange={(e) => setForm({ ...form, command: e.target.value.toLowerCase().replace(/\s+/g, '_') })} placeholder="narxlar" className="pl-6" />
            </div>
            {form.command && !commandOk && <p className="mt-1 text-xs text-red-600">Faqat kichik lotin harflari, raqam va «_». «start» va «menu» band.</p>}
          </div>
        </div>
        <div>
          <Label hint={`${form.text.length} / 4096`}>Javob matni</Label>
          <Textarea rows={8} maxLength={4096} value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} placeholder="Kurslarimiz narxi:&#10;• Ingliz tili — ... so'm/oy&#10;• Matematika — ... so'm/oy" />
          <p className="mt-1 text-xs text-gray-500">Mijoz bu tugmani bossa, bot AI'siz shu matnni (va rasmlarni) darhol yuboradi.</p>
        </div>
        <label className="flex items-center gap-3">
          <Toggle checked={form.is_active} onChange={(v) => setForm({ ...form, is_active: v })} />
          <span className="text-sm text-gray-700">Faol (botda ko'rinadi)</span>
        </label>
      </div>
    </Modal>
  )
}

function ItemImages({ item }: { item: MenuItem }) {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const upload = useMutation({
    mutationFn: (files: File[]) => botMenuApi.uploadImages(item.id, files),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['bot-menu'] }),
    onError: (e) => toast.error(errorMessage(e)),
  })
  const remove = useMutation({
    mutationFn: (id: string) => botMenuApi.removeImage(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['bot-menu'] }),
    onError: (e) => toast.error(errorMessage(e)),
  })
  const left = MAX_IMAGES - item.images.length

  return (
    <div className="flex flex-wrap items-center gap-2">
      {item.images.map((img) => (
        <div key={img.id} className="group relative h-16 w-16 overflow-hidden rounded-lg ring-1 ring-gray-200">
          <AuthImage imageId={img.id} className="h-full w-full object-cover" />
          <button
            onClick={() => remove.mutate(img.id)}
            className="absolute right-0.5 top-0.5 hidden rounded-full bg-white/90 p-0.5 text-red-600 shadow group-hover:block"
            title="O'chirish"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      {left > 0 && (
        <button
          onClick={() => input.current?.click()}
          disabled={upload.isPending}
          className="flex h-16 w-16 flex-col items-center justify-center gap-0.5 rounded-lg border-2 border-dashed border-gray-300 text-gray-400 hover:border-brand-400 hover:text-brand-600"
        >
          <ImagePlus className="h-5 w-5" />
          <span className="text-[10px]">{upload.isPending ? '...' : 'Rasm'}</span>
        </button>
      )}
      <input
        ref={input}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        multiple
        hidden
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []).slice(0, left)
          const tooBig = files.find((f) => f.size > 5 * 1024 * 1024)
          if (tooBig) toast.error(`${tooBig.name}: 5 MB dan katta`)
          else if (files.length) upload.mutate(files)
          e.target.value = ''
        }}
      />
    </div>
  )
}

export default function BotMenuPage() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['bot-menu'], queryFn: botMenuApi.get })
  const [greeting, setGreeting] = useState('')
  const [editing, setEditing] = useState<MenuItem | null>(null)
  const [modalOpen, setModalOpen] = useState(false)

  useEffect(() => setGreeting(data?.greeting ?? ''), [data?.greeting])

  const saveGreeting = useMutation({
    mutationFn: () => botMenuApi.setGreeting(greeting),
    onSuccess: () => {
      toast.success('Salomlashish matni saqlandi')
      qc.invalidateQueries({ queryKey: ['bot-menu'] })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const remove = useMutation({
    mutationFn: (id: string) => botMenuApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['bot-menu'] }),
    onError: (e) => toast.error(errorMessage(e)),
  })
  const reorder = useMutation({
    mutationFn: (ids: string[]) => botMenuApi.reorder(ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['bot-menu'] }),
    onError: (e) => toast.error(errorMessage(e)),
  })

  function move(index: number, dir: -1 | 1) {
    if (!data) return
    const ids = data.items.map((i) => i.id)
    const j = index + dir
    if (j < 0 || j >= ids.length) return
    ;[ids[index], ids[j]] = [ids[j], ids[index]]
    reorder.mutate(ids)
  }

  return (
    <>
      <PageHeader
        title="Bot menyusi"
        subtitle="Telegram botidagi tugmalar. Mijoz bo'limni tanlasa, AI'siz tayyor javob (matn + rasm) yuboriladi."
        action={<Button icon={<Plus className="h-4 w-4" />} onClick={() => { setEditing(null); setModalOpen(true) }}>Bo'lim qo'shish</Button>}
      />
      {isLoading && <Loading />}
      {data && (
        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Salomlashish matni"
              subtitle="/start bosilganda menyu tugmalari bilan birga yuboriladi"
              action={<Button size="sm" icon={<Save className="h-3.5 w-3.5" />} disabled={greeting === data.greeting} loading={saveGreeting.isPending} onClick={() => saveGreeting.mutate()}>Saqlash</Button>}
            />
            <div className="p-5">
              <Textarea rows={4} value={greeting} onChange={(e) => setGreeting(e.target.value)} placeholder="Assalomu alaykum! 👋 Wunderkind o'quv markaziga xush kelibsiz. Quyidagi bo'limlardan birini tanlang yoki savolingizni yozing." />
            </div>
          </Card>

          <Card>
            <CardHeader title="Bo'limlar" subtitle={`${data.items.length} ta`} />
            {data.items.length === 0 ? (
              <Empty
                icon={<Bot className="h-6 w-6" />}
                title="Hali bo'lim yo'q"
                text="Masalan: «📚 Kurslar», «💰 Narxlar», «📍 Manzil», «🎁 Bepul sinov darsi»."
                action={<Button icon={<Plus className="h-4 w-4" />} onClick={() => { setEditing(null); setModalOpen(true) }}>Bo'lim qo'shish</Button>}
              />
            ) : (
              <ul className="divide-y divide-gray-100">
                {data.items.map((item, i) => (
                  <li key={item.id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start">
                    <div className="flex shrink-0 gap-1 sm:flex-col">
                      <button disabled={i === 0 || reorder.isPending} onClick={() => move(i, -1)} className="rounded p-1 text-gray-400 hover:bg-gray-100 disabled:opacity-30"><ArrowUp className="h-4 w-4" /></button>
                      <button disabled={i === data.items.length - 1 || reorder.isPending} onClick={() => move(i, 1)} className="rounded p-1 text-gray-400 hover:bg-gray-100 disabled:opacity-30"><ArrowDown className="h-4 w-4" /></button>
                    </div>
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-medium text-gray-900">{item.title}</p>
                        <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">/{item.command}</code>
                        {!item.is_active && <Badge>Nofaol</Badge>}
                      </div>
                      {item.text && <p className="line-clamp-3 whitespace-pre-wrap text-sm text-gray-600">{item.text}</p>}
                      <ItemImages item={item} />
                    </div>
                    <div className="flex shrink-0 gap-1">
                      <Button variant="ghost" size="sm" icon={<Pencil className="h-4 w-4" />} onClick={() => { setEditing(item); setModalOpen(true) }}>Tahrirlash</Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-red-600 hover:bg-red-50"
                        icon={<Trash2 className="h-4 w-4" />}
                        onClick={() => { if (window.confirm(`«${item.title}» bo'limi o'chirilsinmi?`)) remove.mutate(item.id) }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
      <ItemModal item={editing} open={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  )
}
