import React from 'react';
import { Alert } from '@agentscope-ai/design';

function resolveValue(value, dataModel) {
  if (typeof value === 'string') return value;
  if (!value?.path || !value.path.startsWith('/')) return '';
  return value.path.slice(1).split('/').reduce((current, key) => current?.[key], dataModel) ?? '';
}

export function A2uiSurface({ envelope }) {
  const surface = envelope?.version === 'v1.0' ? envelope.createSurface : null;
  if (!surface || !Array.isArray(surface.components)) return null;
  const components = new Map(surface.components.map((component) => [component.id, component]));
  let invalid = false;
  const render = (id) => {
    const component = components.get(id);
    if (!component) return null;
    if (component.component === 'Text') {
      return <p key={id} className="a2ui-text">{String(resolveValue(component.text, surface.dataModel))}</p>;
    }
    if (component.component === 'Column') {
      return <div key={id} className="a2ui-column">{(component.children || []).map(render)}</div>;
    }
    invalid = true;
    return null;
  };
  const content = render('root');
  if (invalid) return <Alert type="warning" message="该界面包含未授权组件，已停止渲染。" showIcon />;
  return <section className="a2ui-surface" aria-live="polite">{content}</section>;
}
