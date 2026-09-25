import { api } from './client'
import type { AgentOutput, Channel, ChatTurn } from './types'

export const playgroundApi = {
  run: (messages: ChatTurn[], channel: Channel, is_comment: boolean) =>
    api.post<AgentOutput>('/playground', { messages, channel, is_comment }).then((r) => r.data),
}
