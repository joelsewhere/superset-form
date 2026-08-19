import { z } from 'zod'
import type { FormFieldSpec } from '../api/client'

/**
 * Build a validator from the field specs the API serves, so client-side
 * validation always matches the server's without a second definition.
 */
export function buildZodSchema(fields: FormFieldSpec[]): z.ZodTypeAny {
  const shape: Record<string, z.ZodTypeAny> = {}

  for (const field of fields) {
    let validator: z.ZodTypeAny

    switch (field.type) {
      case 'number': {
        let numeric = z.coerce.number({ invalid_type_error: `${field.label} must be a number` })
        if (field.min !== null) numeric = numeric.min(field.min, `Minimum is ${field.min}`)
        if (field.max !== null) numeric = numeric.max(field.max, `Maximum is ${field.max}`)
        validator = numeric
        break
      }
      case 'select': {
        const options = field.options ?? []
        validator = options.length
          ? z.enum(options as [string, ...string[]], {
              errorMap: () => ({ message: `Choose a ${field.label.toLowerCase()}` }),
            })
          : z.string()
        break
      }
      case 'date':
        validator = z
          .string()
          .regex(/^\d{4}-\d{2}-\d{2}$/, `${field.label} must be a valid date`)
        break
      default:
        validator = z.string()
    }

    if (field.required) {
      // An untouched text input submits '', which passes z.string() — reject
      // it explicitly so required fields actually behave as required.
      if (validator instanceof z.ZodString) {
        validator = validator.min(1, `${field.label} is required`)
      }
    } else {
      validator = validator.optional().or(z.literal(''))
    }

    shape[field.name] = validator
  }

  return z.object(shape)
}
