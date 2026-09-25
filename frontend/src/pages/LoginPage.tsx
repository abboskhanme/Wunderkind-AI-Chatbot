import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { errorMessage } from '@/api/client'
import { Button, Input, Label } from '@/components/ui'
import { useAuth } from '@/lib/auth'

export default function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/" replace />

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      await login(username.trim(), password)
      navigate('/', { replace: true })
    } catch (err) {
      toast.error(errorMessage(err, "Login yoki parol noto'g'ri"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-gradient-to-br from-brand-50 via-white to-violet-50 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-600 text-lg font-bold text-white">W</div>
          <h1 className="text-xl font-semibold text-gray-900">Wunderkind AI Agent</h1>
          <p className="mt-1 text-sm text-gray-500">Boshqaruv paneliga kirish</p>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-2xl bg-white p-6 shadow-sm ring-1 ring-gray-200">
          <div>
            <Label>Login</Label>
            <Input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" required />
          </div>
          <div>
            <Label>Parol</Label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
          </div>
          <Button type="submit" className="w-full" loading={busy}>
            Kirish
          </Button>
        </form>
      </div>
    </div>
  )
}
