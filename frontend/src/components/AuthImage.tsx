import { useEffect, useRef, useState } from 'react'
import { botMenuApi } from '@/api/botMenu'

/**
 * Image loaded through the authenticated API client. Defaults to a bot menu image;
 * pass `load` for other endpoints (e.g. funnel message images). To force a reload
 * after the image behind the same id was replaced, change the component `key`.
 */
export function AuthImage({ imageId, className, load }: {
  imageId: string
  className?: string
  load?: (imageId: string) => Promise<Blob>
}) {
  const [src, setSrc] = useState<string>()
  // Kept in a ref so an inline `load` arrow does not refetch on every render.
  const loader = useRef(load ?? botMenuApi.imageBlob)
  loader.current = load ?? botMenuApi.imageBlob

  useEffect(() => {
    let url: string | undefined
    let cancelled = false
    loader
      .current(imageId)
      .then((blob) => {
        if (cancelled) return
        url = URL.createObjectURL(blob)
        setSrc(url)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [imageId])

  if (!src) return <div className={`animate-pulse bg-gray-100 ${className ?? ''}`} />
  return <img src={src} alt="" className={className} />
}
