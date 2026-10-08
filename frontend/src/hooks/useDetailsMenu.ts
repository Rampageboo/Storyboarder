import { useCallback, useEffect, useRef } from 'react'

/** Close a <details> menu when focus or a click leaves it, or on Escape. */
export function useDetailsMenu() {
  const ref = useRef<HTMLDetailsElement | null>(null)
  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      const el = ref.current
      if (el?.open && !el.contains(event.target as Node)) el.open = false
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && ref.current?.open) ref.current.open = false
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [])
  const close = useCallback(() => { if (ref.current) ref.current.open = false }, [])
  return { ref, close }
}
