import React, { useEffect, useId, useRef, useState } from 'react';
import { Sender } from '@agentscope-ai/chat';
import { filterSkillCommands } from '../../frontend/src/utils/skillCommands';

export function AgentMessageInput({ senderRef, catalog, draft, disabled, loading, onChange, onFocus, onSubmit }) {
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [selected, setSelected] = useState(0);
  const [composing, setComposing] = useState(false);
  const compositionActive = useRef(false);
  const listId = useId();
  const list = useRef(null);
  const options = filterSkillCommands(catalog, draft);
  const open = focused && !disabled && !loading && !composing && !dismissed && options.length > 0;
  const active = selected < options.length ? selected : 0;
  const optionId = index => listId + '-' + index;

  useEffect(() => {
    if (!open || !list.current) return;
    const menu = list.current;
    const option = menu.children[active];
    const bounds = menu.getBoundingClientRect();
    const current = option.getBoundingClientRect();
    if (current.top < bounds.top) menu.scrollTop -= bounds.top - current.top;
    else if (current.bottom > bounds.bottom) menu.scrollTop += current.bottom - bounds.bottom;
  }, [open, active, options.length]);

  function select(option) {
    setDismissed(true);
    setSelected(0);
    onChange(option.value.trimEnd() + ' ');
    senderRef.current?.focus?.();
  }

  function updateComposition(active) {
    compositionActive.current = active;
    setComposing(active);
  }

  function handleKeys(event) {
    const native = event.nativeEvent;
    if (compositionActive.current || native.isComposing || native.keyCode === 229) {
      // Keep native IME selection while preventing Sender from treating confirmation as a send.
      if (event.key === 'Enter' || native.keyCode === 13) event.stopPropagation();
      return;
    }
    if (!open || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return;
    switch (event.key) {
      case 'ArrowDown':
        setSelected((active + 1) % options.length);
        break;
      case 'ArrowUp':
        setSelected((active - 1 + options.length) % options.length);
        break;
      case 'Enter':
      case 'Tab':
        select(options[active]);
        break;
      case 'Escape':
        setDismissed(true);
        break;
      default:
        return;
    }
    event.preventDefault();
    event.stopPropagation();
  }

  return (
    <div className="agent-message-input"
      onKeyDownCapture={handleKeys}
      onBlurCapture={event => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setFocused(false);
          updateComposition(false);
        }
      }}
      onCompositionStart={() => updateComposition(true)}
      onCompositionEnd={() => updateComposition(false)}
    >
      {open && (
        <div className="agent-command-menu">
          <div id={listId} ref={list} role="listbox" aria-label="技能命令">
            {options.map((option, index) => (
              <button key={option.value} id={optionId(index)} type="button" role="option" tabIndex={-1}
                aria-selected={index === active} onMouseDown={event => event.preventDefault()} onClick={() => select(option)}
              >
                <strong>{option.label}</strong>
                <span>{option.description}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      <span className="composer-a11y-only" role="status">{open ? options.length + ' 个技能命令建议' : ''}</span>
      <Sender className="harness-composer-sender" actions={() => null} styles={{ input: { minHeight: 32 } }}
        ref={senderRef} disabled={disabled} loading={loading} value={draft}
        aria-label="聊天消息或技能命令" aria-autocomplete="list" aria-haspopup="listbox"
        aria-controls={open ? listId : undefined} aria-activedescendant={open ? optionId(active) : undefined}
        placeholder="输入消息，/ 选技能" onSubmit={text => onSubmit(text)}
        onFocus={() => { setFocused(true); onFocus(); }}
        onChange={value => { setDismissed(false); setSelected(0); onChange(value); }}
      />
    </div>
  );
}
