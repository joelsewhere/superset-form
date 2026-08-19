import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../api/client'

/** Picks which saved workspace is open, and creates new ones. */
export function ViewSwitcher({
  activeViewId,
  onSelect,
}: {
  activeViewId: number | null
  onSelect: (viewId: number) => void
}) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')

  const views = useQuery({ queryKey: ['views'], queryFn: api.listViews })

  const create = useMutation({
    mutationFn: (viewName: string) => api.createView(viewName),
    onSuccess: (view) => {
      queryClient.invalidateQueries({ queryKey: ['views'] })
      setCreating(false)
      setName('')
      onSelect(view.id)
    },
  })

  return (
    <div className="ff-viewswitcher">
      <label className="ff-viewswitcher__label" htmlFor="view-select">
        View
      </label>
      <select
        id="view-select"
        className="ff-input ff-input--compact"
        value={activeViewId ?? ''}
        onChange={(e) => onSelect(Number(e.target.value))}
        disabled={views.isPending}
      >
        {views.data?.map((view) => (
          <option key={view.id} value={view.id}>
            {view.name}
            {view.is_default ? ' (default)' : ''}
          </option>
        ))}
      </select>

      {creating ? (
        <form
          className="ff-viewswitcher__create"
          onSubmit={(e) => {
            e.preventDefault()
            if (name.trim()) create.mutate(name.trim())
          }}
        >
          <input
            className="ff-input ff-input--compact"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="View name"
            autoFocus
          />
          <button className="ff-button ff-button--small" type="submit">
            Create
          </button>
          <button
            className="ff-button ff-button--ghost ff-button--small"
            type="button"
            onClick={() => setCreating(false)}
          >
            Cancel
          </button>
        </form>
      ) : (
        <button
          className="ff-button ff-button--ghost ff-button--small"
          type="button"
          onClick={() => setCreating(true)}
        >
          + New view
        </button>
      )}

      {create.isError && <span className="ff-error-inline">{create.error.message}</span>}
    </div>
  )
}
