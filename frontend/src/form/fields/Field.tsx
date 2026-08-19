import type { UseFormRegisterReturn } from 'react-hook-form'
import type { FormFieldSpec } from '../../api/client'

interface FieldProps {
  spec: FormFieldSpec
  registration: UseFormRegisterReturn
  error?: string
}

/** Renders one input from its spec. One component per type would be more
 *  files than this earns — the shapes are close enough to switch on. */
export function Field({ spec, registration, error }: FieldProps) {
  const id = `field-${spec.name}`
  const describedBy = [
    spec.help_text ? `${id}-help` : null,
    error ? `${id}-error` : null,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className="ff-field">
      <label className="ff-field__label" htmlFor={id}>
        {spec.label}
        {!spec.required && <span className="ff-field__optional"> (optional)</span>}
      </label>

      {spec.type === 'select' ? (
        <select
          id={id}
          className="ff-input"
          defaultValue=""
          aria-invalid={Boolean(error)}
          aria-describedby={describedBy || undefined}
          {...registration}
        >
          <option value="" disabled>
            Select…
          </option>
          {(spec.options ?? []).map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : spec.type === 'textarea' ? (
        <textarea
          id={id}
          className="ff-input ff-input--textarea"
          rows={3}
          placeholder={spec.placeholder ?? undefined}
          aria-invalid={Boolean(error)}
          aria-describedby={describedBy || undefined}
          {...registration}
        />
      ) : (
        <input
          id={id}
          className="ff-input"
          type={spec.type === 'number' ? 'number' : spec.type === 'date' ? 'date' : 'text'}
          step={spec.step ?? undefined}
          min={spec.min ?? undefined}
          max={spec.max ?? undefined}
          placeholder={spec.placeholder ?? undefined}
          aria-invalid={Boolean(error)}
          aria-describedby={describedBy || undefined}
          {...registration}
        />
      )}

      {spec.help_text && (
        <p id={`${id}-help`} className="ff-field__help">
          {spec.help_text}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="ff-field__error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
