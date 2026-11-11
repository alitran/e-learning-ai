import DOMPurify from 'dompurify';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import { marked } from 'marked';

marked.use({
  extensions: [{
    name: 'math',
    level: 'inline',
    start(source) {
      const marker = /\$\$?|\\\[|\\\(/.exec(source);
      return marker?.index;
    },
    tokenizer(source) {
      const match = /^\$\$([\s\S]+?)\$\$|^\\\[([\s\S]+?)\\\]|^\$([^$\n]+?)\$|^\\\(([^]*?)\\\)/.exec(source);
      if (!match) return;
      const displayMode = Boolean(match[1] || match[2]);
      return {
        type: 'math',
        raw: match[0],
        text: match[1] ?? match[2] ?? match[3] ?? match[4],
        displayMode
      };
    },
    renderer(token) {
      return katex.renderToString(token.text, {
        displayMode: token.displayMode,
        throwOnError: false
      });
    }
  }]
});

function normalizeMathMarkup(content: string): string {
  const protectedSegments: string[] = [];
  const restoredEscapes = content.replace(/\f(?=rac\{)/g, '\\f');
  const source = restoredEscapes.replace(
    /```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`|\$\$[\s\S]*?\$\$|\$[^$\n]*\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)/g,
    (segment) => {
      if (segment.startsWith('`') && /\\+cdot/.test(segment)) {
        return segment.slice(1, -1).replace(/\\+cdot/g, '·');
      }
      const marker = `\uE000${protectedSegments.length}\uE001`;
      protectedSegments.push(segment);
      return marker;
    }
  );
  const fractionMarkup = source.replace(
    /(^|[^\w\\-])(-?\\frac\{[^{}\s]+\}\{[^{}\s]+\}(?:[A-Za-z]+(?:[_^]\{?[A-Za-z0-9]+\}?)?)*)/g,
    (_match, prefix: string, expression: string) => `${prefix}\\(${expression}\\)`
  );

  return fractionMarkup
    .replace(/\\+cdot/g, '·')
    .replace(/&#x20;/gi, ' ')
    .replace(/\uE000(\d+)\uE001/g, (_marker, index: string) => protectedSegments[Number(index)] ?? '');
}

export function renderMarkdownHtml(content: string): string {
  return DOMPurify.sanitize(marked.parse(normalizeMathMarkup(content)) as string);
}

export function renderInlineMarkdownHtml(content: string): string {
  return DOMPurify.sanitize(marked.parseInline(normalizeMathMarkup(content)) as string);
}
