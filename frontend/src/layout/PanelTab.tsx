import type { IDockviewPanelHeaderProps } from 'dockview'
import { useCollapseContext } from './CollapseContext'

/**
 * The panel's tab — which is also the handle you drag to re-dock it, and so
 * the natural target for double-click-to-collapse.
 *
 * A custom tab is used rather than dockview's default because the default
 * binds its own double-click behaviour.
 */
export function PanelTab(props: IDockviewPanelHeaderProps) {
  const { toggle } = useCollapseContext()

  const handleDoubleClick = (event: React.MouseEvent) => {
    event.preventDefault()
    event.stopPropagation()
    const group = props.api.group
    if (group) toggle(group)
  }

  return (
    <div
      className="ff-tab"
      onDoubleClick={handleDoubleClick}
      title="Drag to re-dock · double-click to collapse"
    >
      <span className="ff-tab__title">{props.api.title}</span>
    </div>
  )
}
