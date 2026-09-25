import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Pencil, Plus, Trash2, Users } from 'lucide-react'
import { usersApi, type UserPatch } from '@/api/users'
import { errorMessage } from '@/api/client'
import type { Role, User } from '@/api/types'
import { Badge, Button, Card, Empty, Input, Label, Loading, Modal, PageHeader, Select, Toggle } from '@/components/ui'
import { useAuth } from '@/lib/auth'
import { USER_ROLE_LABELS } from '@/lib/labels'
import { fmtDate } from '@/lib/format'

interface Form {
  username: string
  full_name: string
  password: string
  role: Role
  is_active: boolean
}

const EMPTY: Form = { username: '', full_name: '', password: '', role: 'operator', is_active: true }

function UserModal({ user, open, onClose }: { user: User | null; open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const { user: me } = useAuth()
  const [form, setForm] = useState<Form>(EMPTY)
  useEffect(() => {
    if (open) setForm(user ? { username: user.username, full_name: user.full_name, password: '', role: user.role, is_active: user.is_active } : EMPTY)
  }, [open, user])

  const save = useMutation({
    mutationFn: () => {
      if (!user) return usersApi.create({ username: form.username.trim(), full_name: form.full_name.trim(), password: form.password, role: form.role })
      const body: UserPatch = { full_name: form.full_name.trim(), role: form.role, is_active: form.is_active }
      if (form.password) body.password = form.password
      return usersApi.update(user.id, body)
    },
    onSuccess: () => {
      toast.success('Saqlandi')
      qc.invalidateQueries({ queryKey: ['users'] })
      qc.invalidateQueries({ queryKey: ['assignees'] })
      onClose()
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const isSelf = user?.id === me?.id
  const valid = form.full_name.trim() && (user || (form.username.trim() && form.password.length >= 6)) && (!form.password || form.password.length >= 6)

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={user ? 'Foydalanuvchini tahrirlash' : 'Yangi foydalanuvchi'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Bekor qilish</Button>
          <Button disabled={!valid} loading={save.isPending} onClick={() => save.mutate()}>Saqlash</Button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <Label>Login</Label>
          <Input value={form.username} disabled={Boolean(user)} onChange={(e) => setForm({ ...form, username: e.target.value })} autoComplete="off" />
        </div>
        <div>
          <Label>To'liq ism</Label>
          <Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
        </div>
        <div>
          <Label hint="kamida 6 belgi">{user ? 'Yangi parol (ixtiyoriy)' : 'Parol'}</Label>
          <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" />
        </div>
        <div>
          <Label>Rol</Label>
          <Select value={form.role} disabled={isSelf} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            <option value="operator">Operator — suhbatlar va leadlar</option>
            <option value="admin">Administrator — hammasi</option>
          </Select>
        </div>
        {user && !isSelf && (
          <label className="flex items-center gap-3">
            <Toggle checked={form.is_active} onChange={(v) => setForm({ ...form, is_active: v })} />
            <span className="text-sm text-gray-700">Faol</span>
          </label>
        )}
      </div>
    </Modal>
  )
}

export default function UsersPage() {
  const qc = useQueryClient()
  const { user: me } = useAuth()
  const { data, isLoading } = useQuery({ queryKey: ['users'], queryFn: usersApi.list })
  const [editing, setEditing] = useState<User | null>(null)
  const [open, setOpen] = useState(false)

  const remove = useMutation({
    mutationFn: (id: string) => usersApi.remove(id),
    onSuccess: () => {
      toast.success("O'chirildi")
      qc.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  return (
    <>
      <PageHeader
        title="Foydalanuvchilar"
        subtitle="Panelga kira oladigan xodimlar"
        action={<Button icon={<Plus className="h-4 w-4" />} onClick={() => { setEditing(null); setOpen(true) }}>Qo'shish</Button>}
      />
      <Card className="overflow-hidden">
        {isLoading && <Loading />}
        {data && data.length === 0 && <Empty icon={<Users className="h-6 w-6" />} title="Foydalanuvchilar yo'q" />}
        {data && data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-4 py-3">Ism</th>
                  <th className="px-4 py-3">Login</th>
                  <th className="px-4 py-3">Rol</th>
                  <th className="px-4 py-3">Holat</th>
                  <th className="hidden px-4 py-3 sm:table-cell">Qo'shilgan</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {data.map((u) => (
                  <tr key={u.id}>
                    <td className="px-4 py-3 font-medium text-gray-900">{u.full_name}{u.id === me?.id && <span className="ml-1 text-xs text-gray-400">(siz)</span>}</td>
                    <td className="px-4 py-3 text-gray-600">{u.username}</td>
                    <td className="px-4 py-3">
                      <Badge className={u.role === 'admin' ? 'bg-brand-50 text-brand-700 ring-brand-200' : undefined}>{USER_ROLE_LABELS[u.role]}</Badge>
                    </td>
                    <td className="px-4 py-3">
                      {u.is_active ? <Badge className="bg-emerald-50 text-emerald-700 ring-emerald-200">Faol</Badge> : <Badge>Nofaol</Badge>}
                    </td>
                    <td className="hidden px-4 py-3 text-gray-500 sm:table-cell">{fmtDate(u.created_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" icon={<Pencil className="h-4 w-4" />} onClick={() => { setEditing(u); setOpen(true) }} />
                        {u.id !== me?.id && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-red-600 hover:bg-red-50"
                            icon={<Trash2 className="h-4 w-4" />}
                            onClick={() => { if (window.confirm(`${u.full_name} o'chirilsinmi?`)) remove.mutate(u.id) }}
                          />
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <UserModal user={editing} open={open} onClose={() => setOpen(false)} />
    </>
  )
}
