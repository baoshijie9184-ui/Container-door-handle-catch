import React from 'react';
import { messageBlocks, messageInline } from '../../frontend/src/utils/messageMarkdown.js';
import '../../frontend/src/assets/agent-markdown.css';

// Same text-node Markdown subset as Vue. No HTML, image requests or skill-link rewrite.
function inlineNodes(tokens) {
  return tokens.map((token, key) => {
    if (token.type === 'text') return token.text;
    if (token.type === 'code') return <code key={key}>{token.text}</code>;
    if (token.type === 'link') return <a key={key} href={token.href} {...(token.external ? {target:'_blank', rel:'noopener noreferrer', title:'在新标签页打开外部链接'} : {})}>{inlineNodes(token.children)}</a>;
    const Tag = token.type === 'strong' ? 'strong' : 'em';
    return <Tag key={key}>{inlineNodes(token.children)}</Tag>;
  });
}
const InlineText = ({text}) => <span className="agent-inline">{inlineNodes(messageInline(text))}</span>;

export default function AgentMarkdown({text = '', className = ''}) {
  return <div className={'agent-markdown '+className}>{messageBlocks(text).map(block => {
    if (block.type === 'code') return <section className="agent-code" key={block.id}><header><span>{block.language || '代码'}</span></header><pre tabIndex={0} aria-label={(block.language || '')+'代码，可选中复制'}><code>{block.text}</code></pre></section>;
    if (block.type === 'table') return <div key={block.id} className="agent-markdown-table" role="region" aria-label="计划表格，可横向滚动" tabIndex={0}><table><thead><tr>{block.headers.map((cell,column) => <th key={column} scope="col" style={{textAlign:block.alignments[column]}}><InlineText text={cell}/></th>)}</tr></thead><tbody>{block.rows.map((row,index) => <tr key={index}>{row.map((cell,column) => <td key={column} style={{textAlign:block.alignments[column]}}><InlineText text={cell}/></td>)}</tr>)}</tbody></table></div>;
    if (block.type === 'heading') {const Tag = 'h'+Math.min(block.level+1,6); return <Tag key={block.id}><InlineText text={block.text}/></Tag>;}
    if (block.type === 'rule') return <hr key={block.id}/>;
    if (block.type === 'quote') return <blockquote key={block.id}><InlineText text={block.text}/></blockquote>;
    if (block.type === 'list') {const Tag = block.ordered ? 'ol' : 'ul'; return <Tag key={block.id} start={block.ordered ? block.start : undefined}>{block.items.map((item,index) => <li key={index}><InlineText text={item}/></li>)}</Tag>;}
    return <p key={block.id}><InlineText text={block.text}/></p>;
  })}</div>;
}
