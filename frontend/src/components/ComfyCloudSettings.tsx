import { useEffect, useState } from 'react'
import {
  checkComfyCloud,
  clearComfyCloudKey,
  getComfyCloudStatus,
  setComfyCloudKey,
  type ComfyCloudCheck,
  type ComfyCloudStatus,
} from '../api'

/**
 * Per-machine Comfy Cloud connection. The key goes to the OS credential store via
 * the backend and is never read back into the page.
 */
export function ComfyCloudSettings() {
  const [status, setStatus] = useState<ComfyCloudStatus | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [check, setCheck] = useState<ComfyCloudCheck | null>(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    getComfyCloudStatus().then(setStatus).catch(() => setStatus(null))
  }, [])

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    setMessage('')
    try {
      await action()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const save = () => run(async () => {
    setStatus(await setComfyCloudKey(draft.trim()))
    setDraft('')
    setCheck(null)
    setMessage('Key saved to Windows Credential Manager.')
  })

  const remove = () => run(async () => {
    setStatus(await clearComfyCloudKey())
    setCheck(null)
    setMessage('Key removed from this computer.')
  })

  const test = () => run(async () => {
    setCheck(await checkComfyCloud())
  })

  return (
    <fieldset className="settings-section">
      <legend>Comfy Cloud video</legend>
      <p className="settings-hint">
        Generates board videos on Comfy Cloud ({status?.template || 'Wan 2.2 image-to-video'}). Needs a paid plan.
        Create a key at platform.comfy.org → API Keys.
      </p>
      <div className="settings-key-row">
        <input
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={status?.configured ? 'A key is saved on this computer' : 'Paste API key'}
          aria-label="Comfy Cloud API key"
          disabled={busy}
        />
        <button type="button" onClick={() => void save()} disabled={busy || !draft.trim()}>Save key</button>
      </div>
      <div className="settings-key-row">
        <span className={'settings-key-state' + (status?.configured ? ' is-set' : '')}>
          {status === null ? 'Checking…' : status.configured ? 'Key saved' : 'No key saved'}
        </span>
        <button type="button" className="ghost" onClick={() => void test()} disabled={busy || !status?.configured}>
          {busy ? 'Working…' : 'Test connection'}
        </button>
        <button type="button" className="ghost" onClick={() => void remove()} disabled={busy || !status?.configured}>Remove</button>
      </div>
      {message ? <p className="settings-hint" role="status">{message}</p> : null}
      {check ? (
        <div className={'notice' + (check.ok ? '' : ' is-warn')} role="status">
          {check.ok
            ? `Connected. Every node and model in the template is available (${check.node_count} nodes on the server).`
            : 'Connected, but the template cannot run as is:'}
          {check.missing_nodes.length ? <div>Missing nodes: {check.missing_nodes.join(', ')}</div> : null}
          {check.missing_models.length ? <div>Missing models: {check.missing_models.join(', ')}</div> : null}
          {check.invalid_values.length ? <div>Unsupported values: {check.invalid_values.join('; ')}</div> : null}
        </div>
      ) : null}
    </fieldset>
  )
}
