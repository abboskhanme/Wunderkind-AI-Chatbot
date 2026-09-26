import { api, downloadFile } from './client'
import type { FormInput, FormOut, SubmissionList } from './types'

/** docs/SPEC.md section 15.4 — `/api/forms` (writes: admin only). */
export const formsApi = {
  list: () => api.get<FormOut[]>('/forms').then((r) => r.data),
  get: (id: string) => api.get<FormOut>(`/forms/${id}`).then((r) => r.data),
  create: (body: FormInput) => api.post<FormOut>('/forms', body).then((r) => r.data),
  update: (id: string, body: Partial<FormInput>) =>
    api.patch<FormOut>(`/forms/${id}`, body).then((r) => r.data),
  remove: (id: string) => api.delete(`/forms/${id}`),
  removeSubmission: (formId: string, submissionId: string) =>
    api.delete(`/forms/${formId}/submissions/${submissionId}`),
  submissions: (id: string, page: number, pageSize: number) =>
    api
      .get<SubmissionList>(`/forms/${id}/submissions`, { params: { page, page_size: pageSize } })
      .then((r) => r.data),
  submissionsCsvUrl: (id: string) => `/api/forms/${id}/submissions.csv`,
  /** Fetched with the Authorization header (like the leads export), saved as a file. */
  downloadSubmissionsCsv: (form: Pick<FormOut, 'id' | 'slug'>) =>
    downloadFile(
      formsApi.submissionsCsvUrl(form.id),
      `forma-${form.slug}-${new Date().toISOString().slice(0, 10)}.csv`,
    ),
}
