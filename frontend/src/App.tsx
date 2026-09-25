import { Navigate, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import { Layout } from '@/components/Layout'
import { Loading } from '@/components/ui'
import { isAdmin, useAuth } from '@/lib/auth'
import LoginPage from '@/pages/LoginPage'
import DashboardPage from '@/pages/DashboardPage'
import InboxPage from '@/pages/InboxPage'
import LeadsPage from '@/pages/LeadsPage'
import FunnelPage from '@/pages/FunnelPage'
import KnowledgePage from '@/pages/KnowledgePage'
import BotMenuPage from '@/pages/BotMenuPage'
import PlaygroundPage from '@/pages/PlaygroundPage'
import SettingsPage from '@/pages/SettingsPage'
import UsersPage from '@/pages/UsersPage'

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <Loading />
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

function AdminOnly({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  if (!isAdmin(user)) return <Navigate to="/" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="inbox" element={<InboxPage />} />
        <Route path="inbox/:leadId" element={<InboxPage />} />
        <Route path="leads" element={<LeadsPage />} />
        <Route path="funnel" element={<FunnelPage />} />
        <Route path="knowledge" element={<AdminOnly><KnowledgePage /></AdminOnly>} />
        <Route path="bot-menu" element={<AdminOnly><BotMenuPage /></AdminOnly>} />
        <Route path="playground" element={<AdminOnly><PlaygroundPage /></AdminOnly>} />
        <Route path="settings" element={<AdminOnly><SettingsPage /></AdminOnly>} />
        <Route path="users" element={<AdminOnly><UsersPage /></AdminOnly>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
