import { createContext, useContext } from 'react'

/** Lets panels (Setup in particular) act on the view they are inside. */
const ViewContext = createContext<{ activeViewId: number | null }>({
  activeViewId: null,
})

export const ViewProvider = ViewContext.Provider

export function useActiveViewId(): number | null {
  return useContext(ViewContext).activeViewId
}
