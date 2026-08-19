import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { SchemaForm } from '../form/SchemaForm'

/**
 * A form panel: the entry form for one form definition, plus a strip of its
 * recent rows.
 *
 * The strip exists so a submission is acknowledged instantly and locally,
 * independent of however long Superset takes to re-query.
 */
export function FormPanel({ formId }: { formId: number }) {
  return (
    <div className="ff-panel ff-panel--form">
      <SchemaForm formId={formId} />
      <RecentSubmissions formId={formId} />
    </div>
  )
}

function RecentSubmissions({ formId }: { formId: number }) {
  const { data, isPending } = useQuery({
    queryKey: ['submissions', formId],
    queryFn: () => api.listFormSubmissions(formId, 5),
  })

  return (
    <section className="ff-recent">
      <h2 className="ff-recent__heading">Recent submissions</h2>

      {isPending && <p className="ff-muted">Loading…</p>}
      {data && data.length === 0 && <p className="ff-muted">Nothing submitted yet.</p>}

      <ul className="ff-recent__list">
        {data?.map((submission) => (
          <li key={submission.id} className="ff-recent__item">
            <span className="ff-recent__primary">
              {submission.units} × {submission.product}
            </span>
            <span className="ff-recent__secondary">
              {submission.region} ·{' '}
              {new Date(submission.created_at).toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
              })}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
