import { useRef, useState } from 'react'
import { importScene3d, openBlenderScene } from '../api'
import { useProject } from '../state/ProjectContext'
import './Scene3DPanel.css'

function fileName(path: string) {
  return path.split(/[/\\]/).pop() || path
}

export function Scene3DPanel() {
  const { project, setProject, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const inputRef = useRef<HTMLInputElement | null>(null)

  if (!project) return null

  const scene = (project.settings?.scene3d ?? {}) as { file_path?: string; file_name?: string }
  const scenePath = typeof scene.file_path === 'string' ? scene.file_path : ''
  const sceneName = (typeof scene.file_name === 'string' && scene.file_name) || (scenePath ? fileName(scenePath) : '')
  const hasScene = !!scenePath
  const disabled = busy || projectActionBusy

  const importGlb = (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        setProject(await importScene3d(file))
        setNote(`Imported 3D scene: ${file.name}`)
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  const openBlender = () => {
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        setProject(await openBlenderScene())
        setNote('Opened Blender scene.')
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  // The /ref-scene3d viewer is an existing same-origin window (served by FastAPI).
  const openViewer = () => {
    window.open('/ref-scene3d', '_blank', 'noopener')
  }

  return (
    <section className={`scene3d ${open ? 'is-open' : ''}`}>
      <button type="button" className="scene3d-toggle" onClick={() => setOpen((v) => !v)}>
        <span>Scene 3D</span>
        <span className="scene3d-toggle-icon">{open ? '▾' : '▸'}</span>
      </button>

      {open ? (
        <div className="scene3d-body">
          <div className="scene3d-status">
            {hasScene ? (
              <>
                <span className="scene3d-chip ok">Linked</span>
                <span className="scene3d-path" title={scenePath}>
                  {sceneName}
                </span>
              </>
            ) : (
              <span className="scene3d-chip off">No 3D scene linked</span>
            )}
          </div>
          <div className="scene3d-actions">
            <button type="button" onClick={() => inputRef.current?.click()} disabled={disabled}>
              Import GLB
            </button>
            <button type="button" onClick={() => openBlender()} disabled={disabled} title="Open the project's Blender scene">
              Open in Blender
            </button>
            <button type="button" onClick={() => openViewer()} disabled={!hasScene} title="Open the 3D reference viewer">
              Open 3D viewer
            </button>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept=".glb,.gltf"
            hidden
            onChange={(e) => {
              importGlb(e.target.files?.[0] ?? undefined)
              e.target.value = ''
            }}
          />
          {note ? <div className="scene3d-note">{note}</div> : null}
        </div>
      ) : null}
    </section>
  )
}
