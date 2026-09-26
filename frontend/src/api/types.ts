// Types mirror docs/SPEC.md section 6 field names exactly.

export type Role = 'admin' | 'operator'

export interface User {
  id: string
  username: string
  full_name: string
  role: Role
  is_active: boolean
  created_at: string
}

export interface LoginResponse {
  access_token: string
  token_type: 'bearer'
  user: User
}

export type SettingType = 'text' | 'password' | 'number' | 'select' | 'textarea'

export interface SettingItem {
  key: string
  label: string
  type: SettingType
  secret: boolean
  options: string[]
  placeholder: string
  help: string
  value: string
  masked: string
  is_set: boolean
  from_env: boolean
  default?: string
}

export interface SettingGroup {
  id: string
  title: string
  items: SettingItem[]
}

export interface AgentStatus {
  ai_provider: string
  ai_ready: boolean
  instagram_connected: boolean
  instagram_username: string | null
  instagram_token_issued_at: string | null
  telegram_connected: boolean
  telegram_bot_username: string | null
  notifications_ready: boolean
  public_url: string | null
  webhooks: { instagram: string | null; telegram: string | null }
  /** Public URLs for the Meta App Dashboard (SPEC §12.4); null without PUBLIC_URL */
  legal_urls: {
    privacy: string | null
    terms: string | null
    data_deletion_page: string | null
    data_deletion_callback: string | null
    deauthorize: string | null
  }
  telegram_webhook: {
    state: 'not_configured' | 'no_public_url' | 'polling' | 'ok' | 'wrong_url' | 'error'
    error: string | null
  }
  instagram_ready: boolean
}

export interface AiTestResult {
  ok: boolean
  error?: string
  provider?: string
  model?: string
  reply?: string
}

export interface SettingsResponse {
  groups: SettingGroup[]
  status: AgentStatus
}

export interface Dashboard {
  totals: {
    conversations: number
    messages_in: number
    ai_replies: number
    leads_with_contact: number
    hot: number
    trial: number
    enrolled: number
  }
  today: { conversations: number; messages_in: number; new_leads: number; hot: number }
  by_channel: { channel: string; conversations: number }[]
  by_status: { status: string; count: number }[]
  by_day: { date: string; conversations: number; leads: number }[]
  top_courses: { course: string; count: number }[]
  status: AgentStatus
}

export type Channel = 'instagram' | 'telegram'
export type LeadStatus = 'new' | 'contacted' | 'trial' | 'enrolled' | 'lost'
export type MessageRole = 'user' | 'assistant' | 'operator' | 'system'
export type ReplyWindow = 'open' | 'human_agent' | 'closed'

export interface LeadOut {
  id: string
  channel: Channel
  external_id: string | null
  username: string | null
  source: string
  name: string | null
  contact: string | null
  course_interest: string | null
  student_age: string | null
  preferred_time: string | null
  language: string | null
  intent: string | null
  stage: string | null
  lead_score: number
  summary: string | null
  status: LeadStatus
  note: string | null
  assigned_to_id: string | null
  assigned_to_name: string | null
  message_count: number
  last_customer_at: string | null
  created_at: string
  updated_at: string
  /** Account name from the channel profile (not the name the AI collected) */
  profile_name: string | null
}

/** Account profile from Telegram / Instagram (SPEC §13) */
export interface CustomerProfile {
  channel: Channel
  external_id: string
  username: string | null
  full_name: string | null
  /** Only a phone the person shared themselves (Telegram contact) */
  phone: string | null
  details: {
    language_code?: string
    is_premium?: boolean
    bio?: string
    birthdate?: string
    personal_channel?: string
    followers?: number
    is_verified?: boolean
    follows_us?: boolean
    we_follow?: boolean
  }
  fetched_at: string | null
  updated_at: string
}

export interface Message {
  id: string
  kind: 'dm' | 'comment' | 'note' | 'status'
  role: MessageRole
  text: string | null
  meta: Record<string, unknown>
  created_at: string
}

export interface LeadDetail extends LeadOut {
  messages: Message[]
  profile: CustomerProfile | null
}

export interface LeadList {
  items: LeadOut[]
  total: number
}

export interface InboxItem {
  lead_id: string
  channel: Channel
  username: string | null
  name: string | null
  profile_name: string | null
  contact: string | null
  status: LeadStatus
  lead_score: number
  stage: string | null
  last_message: string | null
  last_message_role: MessageRole | null
  last_message_at: string | null
  unread: number
  window: ReplyWindow
}

export interface LeadPatch {
  status?: LeadStatus
  name?: string | null
  contact?: string | null
  course_interest?: string | null
  student_age?: string | null
  preferred_time?: string | null
  note?: string | null
  assigned_to_id?: string | null
}

export interface ReplyResult {
  sent: boolean
  error?: string
  message?: Message
}

export interface Assignee {
  id: string
  full_name: string
}

export interface MenuImage {
  id: string
  content_type: string
  size_bytes: number
  sort_order: number
}

export interface MenuItem {
  id: string
  command: string
  title: string
  text: string | null
  sort_order: number
  is_active: boolean
  images: MenuImage[]
}

export interface BotMenu {
  greeting: string
  items: MenuItem[]
}

export interface MenuItemInput {
  command: string
  title: string
  text: string
  is_active: boolean
}

export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
}

export interface AgentOutput {
  reply: string
  language: string
  intent: string
  lead_score: number
  is_hot_lead: boolean
  move_to_dm: boolean
  escalate_to_human: boolean
  stage: string
  lead: {
    name: string | null
    contact: string | null
    course_interest: string | null
    student_age: string | null
    preferred_time: string | null
    summary: string | null
  }
}

// --- Lead-magnet funnel (docs/SPEC.md section 10.4) ---------------------------

export type FunnelSource = 'instagram' | 'telegram_channel' | 'telegram_direct'

export type FunnelStep =
  | 'ig_waiting_follow'
  | 'ig_link_sent'
  | 'tg_channel_gate'
  | 'ask_name'
  | 'ask_phone'
  | 'ask_grade'
  | 'pdf_pending'
  | 'pdf_sent'

export type FunnelStatKey =
  | 'comments'
  | 'link_sent'
  | 'bot_started'
  | 'contact_collected'
  | 'pdf_sent'
  | 'booked'
  | 'attended'

export type BookingStatus = 'scheduled' | 'attended' | 'no_show' | 'cancelled'

export interface FunnelStats {
  steps: { key: FunnelStatKey; label: string; count: number }[]
  by_source: { source: FunnelSource; count: number }[]
  bookings: { scheduled: number; attended: number; no_show: number; cancelled: number; today: number }
  by_day: { date: string; entries: number; pdf: number; bookings: number }[]
}

export interface BookingOut {
  id: string
  entry_id: string
  lead_id: string | null
  full_name: string | null
  phone: string | null
  grade: string | null
  starts_at: string
  status: BookingStatus
  note: string | null
  reminder_sent_at: string | null
  created_at: string
  funnel_id: string
  funnel_name: string | null
}

export interface BookingPatch {
  status?: BookingStatus
  note?: string
}

export interface FunnelEntryOut {
  id: string
  source: FunnelSource
  step: FunnelStep
  full_name: string | null
  phone: string | null
  grade: string | null
  ig_username: string | null
  tg_username: string | null
  lead_id: string | null
  pdf_sent_at: string | null
  opted_out: boolean
  booking: BookingOut | null
  messages_sent: number
  created_at: string
  funnel_id: string
  funnel_name: string | null
}

export interface FunnelEntryList {
  items: FunnelEntryOut[]
  total: number
}

export interface FunnelSlot {
  time: string
  free: number
}

export interface FunnelMessageOut {
  id: string
  funnel_id: string
  sort_order: number
  text: string
  delay_minutes: number
  is_active: boolean
  has_image: boolean
  image_content_type: string | null
}

export interface FunnelMessageInput {
  text: string
  delay_minutes: number
  is_active: boolean
}

export interface LeadMagnetInfo {
  filename: string
  size_bytes: number
  updated_at: string
}

export interface SheetTestResult {
  ok: boolean
  error?: string
  title?: string
}

export type TestMessageKind = 'reminder' | 'confirm' | 'sales'

export interface TestMessageInput {
  tg_chat_id: string
  kind: TestMessageKind
  message_id?: string
}

export interface SendResult {
  sent: boolean
  error?: string
}

// --- Multiple funnels (docs/SPEC.md section 11.3) ---------------------------------

export interface FunnelOut {
  id: string
  name: string
  slug: string
  is_active: boolean
  is_default: boolean
  /** Comma separated; empty on the default funnel = global FUNNEL_KEYWORDS */
  keywords: string
  /** Comma separated media ids / permalink shortcodes; empty = any post */
  ig_media_ids: string
  /** Per-funnel overrides of FUNNEL_TEXT_KEYS; missing/empty = global setting */
  texts: Record<string, string>
  sort_order: number
  links: { telegram_channel: string | null; telegram_direct: string | null }
  stats: { entries: number; pdf_sent: number; booked: number }
  has_pdf: boolean
  created_at: string
}

export interface FunnelCreate {
  name: string
  slug?: string
  keywords: string
  ig_media_ids?: string
  is_active?: boolean
  texts?: Record<string, string>
  copy_from_id?: string
}

export interface FunnelPatch {
  name?: string
  slug?: string
  is_active?: boolean
  keywords?: string
  ig_media_ids?: string
  texts?: Record<string, string>
}
