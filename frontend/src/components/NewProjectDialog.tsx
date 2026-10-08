import { useEffect, useRef, useState } from 'react'
import type { ProjectPathRequest } from '../types'
import './NewProjectDialog.css'

type ProjectType = NonNullable<ProjectPathRequest['project_type']>

export function NewProjectDialog({ initialType, onChoose }: {
  initialType: ProjectType
  onChoose: (choice: ProjectType | null) => void
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [projectType, setProjectType] = useState(initialType)

  useEffect(() => {
    const dialog = dialogRef.current
    dialog?.showModal()
    return () => { dialog?.close() }
  }, [])

  return (
    <dialog ref={dialogRef} className="new-project-dialog" aria-labelledby="new-project-title"
      onCancel={(event) => { event.preventDefault(); onChoose(null) }}
      onKeyDown={(event) => event.stopPropagation()}>
      <form onSubmit={(event) => { event.preventDefault(); onChoose(projectType) }}>
        <h2 id="new-project-title">New project</h2>
        <fieldset>
          <legend>What are you creating?</legend>
          <label className="new-project-choice">
            <input type="radio" name="project-type" value="video" checked={projectType === 'video'}
              onChange={() => setProjectType('video')} autoFocus={initialType === 'video'} />
            <span><strong>Video</strong><small>Start in Board for storyboards and animatics.</small></span>
          </label>
          <label className="new-project-choice">
            <input type="radio" name="project-type" value="comic" checked={projectType === 'comic'}
              onChange={() => setProjectType('comic')} autoFocus={initialType === 'comic'} />
            <span><strong>Comic</strong><small>Start in Comic for pages, spreads and long scrolls.</small></span>
          </label>
        </fieldset>
        <div className="new-project-actions">
          <button type="button" onClick={() => onChoose(null)}>Cancel</button>
          <button type="submit">Create</button>
        </div>
      </form>
    </dialog>
  )
}
