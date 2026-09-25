import toast from 'react-hot-toast'

export async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success('Nusxa olindi')
  } catch {
    toast.error("Nusxa olib bo'lmadi")
  }
}
