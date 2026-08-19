import type { IDockviewHeaderActionsProps } from 'dockview'
import { useCollapseContext } from './CollapseContext'

/**
 * Right-aligned actions in each group's header bar: an explicit collapse
 * control (double-click is discoverable only once you know about it) and a
 * layout reset, which is the escape hatch when a persisted layout goes bad.
 */
export function HeaderActions(props: IDockviewHeaderActionsProps) {
  const { toggle, isCollapsed, resetLayout } = useCollapseContext()
  const collapsed = isCollapsed(props.group)

  return (
    <div className="ff-header-actions">
      <button
        type="button"
        className="ff-icon-button"
        onClick={() => toggle(props.group)}
        title={collapsed ? 'Expand panel' : 'Collapse panel'}
        aria-label={collapsed ? 'Expand panel' : 'Collapse panel'}
      >
        {collapsed ? '⟩' : '⟨'}
      </button>
      <button
        type="button"
        className="ff-icon-button"
        onClick={resetLayout}
        title="Reset layout"
        aria-label="Reset layout"
      >
        ⟲
      </button>
    </div>
  )
}
