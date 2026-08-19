import { useMemo } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { FormFieldSpec } from '../api/client'
import { publish } from '../events/bus'
import { buildZodSchema } from './buildZodSchema'
import { Field } from './fields/Field'

export function SchemaForm({ formId }: { formId: number }) {
  const queryClient = useQueryClient()

  const form = useQuery({
    queryKey: ['form', formId],
    queryFn: () => api.getForm(formId),
  })

  if (form.isPending) return <p className="ff-muted">Loading form…</p>
  if (form.error) {
    return (
      <p className="ff-error-banner" role="alert">
        Could not load the form: {form.error.message}
      </p>
    )
  }

  return (
    <SchemaFormFields
      formId={formId}
      fields={form.data.fields}
      dashboardIds={form.data.dashboard_ids}
      queryClient={queryClient}
    />
  )
}

function SchemaFormFields({
  formId,
  fields,
  dashboardIds,
  queryClient,
}: {
  formId: number
  fields: FormFieldSpec[]
  dashboardIds: number[]
  queryClient: ReturnType<typeof useQueryClient>
}) {
  const schema = useMemo(() => buildZodSchema(fields), [fields])

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({ resolver: zodResolver(schema as never) })

  const mutation = useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      api.createSubmission(formId, values),
    onSuccess: () => {
      reset()
      queryClient.invalidateQueries({ queryKey: ['submissions', formId] })
      // Carries the dashboards this form feeds, so only those panels refresh.
      publish('submission:created', { formId, dashboardIds })
    },
  })

  const onSubmit = handleSubmit((values) => {
    // Drop empty optional fields rather than sending '' for a nullable column.
    const cleaned = Object.fromEntries(
      Object.entries(values).filter(([, value]) => value !== '' && value !== undefined),
    )
    return mutation.mutateAsync(cleaned)
  })

  return (
    <form className="ff-form" onSubmit={onSubmit} noValidate>
      {fields.map((spec) => (
        <Field
          key={spec.name}
          spec={spec}
          registration={register(spec.name)}
          error={errors[spec.name]?.message as string | undefined}
        />
      ))}

      {mutation.isError && (
        <p className="ff-error-banner" role="alert">
          {mutation.error.message}
        </p>
      )}

      <button className="ff-button" type="submit" disabled={isSubmitting || mutation.isPending}>
        {mutation.isPending ? 'Submitting…' : 'Submit'}
      </button>

      {dashboardIds.length === 0 && (
        <p className="ff-muted ff-small">
          This form is not linked to any dashboard, so submissions will not
          update anything. Link one in Setup.
        </p>
      )}
    </form>
  )
}
