import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import './ContextMenu.css'

export type ContextMenuItem =
  | {
      kind?: 'item'
      label: string
      onSelect: () => void
      disabled?: boolean
      danger?: boolean
    }
  | {
      kind: 'label'
      label: string
    }
  | {
      kind: 'separator'
    }

export interface ContextMenuState {
  x: number
  y: number
}

interface ContextMenuProps {
  menu: ContextMenuState | null
  items: ContextMenuItem[]
  onClose: () => void
  ariaLabel?: string
}

const VIEWPORT_MARGIN = 8

export function ContextMenu({ menu, items, onClose, ariaLabel = 'Context menu' }: ContextMenuProps) {
  const ref = useRef<HTMLDivElement | null>(null)
  const [position, setPosition] = useState({ x: 0, y: 0 })

  useLayoutEffect(() => {
    if (!menu) return
    const node = ref.current
    if (!node) {
      setPosition({ x: menu.x, y: menu.y })
      return
    }
    const rect = node.getBoundingClientRect()
    const maxX = window.innerWidth - rect.width - VIEWPORT_MARGIN
    const maxY = window.innerHeight - rect.height - VIEWPORT_MARGIN
    setPosition({
      x: Math.max(VIEWPORT_MARGIN, Math.min(menu.x, maxX)),
      y: Math.max(VIEWPORT_MARGIN, Math.min(menu.y, maxY)),
    })
  }, [menu, items])

  useEffect(() => {
    if (!menu) return
    const onPointerDown = (event: PointerEvent) => {
      if (ref.current?.contains(event.target as Node)) return
      onClose()
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('pointerdown', onPointerDown)
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('blur', onClose)
    return () => {
      window.removeEventListener('pointerdown', onPointerDown)
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('blur', onClose)
    }
  }, [menu, onClose])

  if (!menu) return null

  return (
    <div
      ref={ref}
      className="context-menu"
      role="menu"
      aria-label={ariaLabel}
      style={{ left: position.x, top: position.y }}
    >
      {items.map((item, index) => {
        if (item.kind === 'separator') {
          return <div key={`sep-${index}`} className="context-menu-separator" role="separator" />
        }
        if (item.kind === 'label') {
          return (
            <div key={`label-${index}`} className="context-menu-label">
              {item.label}
            </div>
          )
        }
        return (
          <button
            key={`${item.label}-${index}`}
            type="button"
            role="menuitem"
            className={item.danger ? 'is-danger' : ''}
            disabled={item.disabled}
            onClick={() => {
              if (item.disabled) return
              onClose()
              item.onSelect()
            }}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}
