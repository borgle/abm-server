/**
 * Minimal, dependency-free Markdown renderer for the creation studio preview.
 *
 * Security model: the source is HTML-escaped first, then a small subset of
 * Markdown is turned into tags. Raw HTML in the source stays visible text, and
 * links/images are limited to http(s), mailto and site-relative URLs.
 *
 * Supported: headings, paragraphs/line breaks, bold/italic/strikethrough,
 * inline code, fenced code, blockquotes, ordered/unordered lists, horizontal
 * rules, links, images and GFM tables.
 */

const ESCAPE_MAP = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ESCAPE_MAP[character]);
}

function safeUrl(raw, { image = false } = {}) {
  const url = String(raw || "").trim();
  if (!url) return "";
  if (url.startsWith("/") && !url.startsWith("//")) return url;
  if (image) {
    return /^https?:\/\//i.test(url) ? url : "";
  }
  return /^(https?:\/\/|mailto:)/i.test(url) ? url : "";
}

const INLINE_CODE = /\u0000(\d+)\u0000/g;

function renderInline(text, store) {
  let value = text;
  value = value.replace(/`([^`\n]+)`/g, (_match, code) => {
    const token = `\u0000${store.length}\u0000`;
    store.push(`<code>${code}</code>`);
    return token;
  });
  value = value.replace(
    /!\[([^\]]*)\]\(([^)\s]+)\)/g,
    (match, alt, url) => {
      const safe = safeUrl(url, { image: true });
      return safe ? `<img src="${safe}" alt="${alt}" loading="lazy" />` : match;
    },
  );
  value = value.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label, url) => {
    const safe = safeUrl(url);
    if (!safe) return match;
    return `<a href="${safe}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });
  value = value.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  value = value.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
  value = value.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  value = value.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
  value = value.replace(INLINE_CODE, (_match, index) => store[Number(index)] ?? "");
  return value;
}

const HEADING = /^(#{1,6})\s+(.*)$/;
const UL_ITEM = /^(\s*)[-*+]\s+(.*)$/;
const OL_ITEM = /^(\s*)\d+[.)]\s+(.*)$/;
const HR = /^\s*([-*_])\1{2,}\s*$/;
const TABLE_DIVIDER = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/;

function splitRow(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

export function renderMarkdown(source) {
  const escaped = escapeHtml(String(source ?? "").replace(/\r\n/g, "\n"));
  const lines = escaped.split("\n");
  const store = [];
  const html = [];
  let index = 0;

  const inline = (text) => renderInline(text, store);

  while (index < lines.length) {
    const line = lines[index];

    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = line.match(/^\s*```(.*)$/);
    if (fence) {
      const language = fence[1].trim();
      const body = [];
      index += 1;
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) {
        body.push(lines[index]);
        index += 1;
      }
      index += 1;
      const lang = language ? ` class="language-${language.replace(/[^\w-]/g, "")}"` : "";
      html.push(`<pre><code${lang}>${body.join("\n")}</code></pre>`);
      continue;
    }

    const heading = line.match(HEADING);
    if (heading) {
      const level = heading[1].length;
      html.push(`<h${level}>${inline(heading[2].trim())}</h${level}>`);
      index += 1;
      continue;
    }

    if (HR.test(line)) {
      html.push("<hr />");
      index += 1;
      continue;
    }

    if (/^\s*&gt;\s?/.test(line)) {
      const body = [];
      while (index < lines.length && /^\s*&gt;\s?/.test(lines[index])) {
        body.push(lines[index].replace(/^\s*&gt;\s?/, ""));
        index += 1;
      }
      html.push(`<blockquote>${body.map((item) => inline(item)).join("<br />")}</blockquote>`);
      continue;
    }

    if (
      line.includes("|") &&
      index + 1 < lines.length &&
      TABLE_DIVIDER.test(lines[index + 1])
    ) {
      const header = splitRow(line);
      index += 2;
      const rows = [];
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        rows.push(splitRow(lines[index]));
        index += 1;
      }
      const head = header.map((cell) => `<th>${inline(cell)}</th>`).join("");
      const body = rows
        .map(
          (row) =>
            `<tr>${header
              .map((_, column) => `<td>${inline(row[column] ?? "")}</td>`)
              .join("")}</tr>`,
        )
        .join("");
      html.push(`<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`);
      continue;
    }

    if (UL_ITEM.test(line) || OL_ITEM.test(line)) {
      const ordered = OL_ITEM.test(line);
      const pattern = ordered ? OL_ITEM : UL_ITEM;
      const items = [];
      while (index < lines.length) {
        const item = lines[index].match(pattern);
        if (!item) break;
        items.push(`<li>${inline(item[2])}</li>`);
        index += 1;
      }
      const tag = ordered ? "ol" : "ul";
      html.push(`<${tag}>${items.join("")}</${tag}>`);
      continue;
    }

    const paragraph = [];
    while (index < lines.length) {
      const current = lines[index];
      if (
        !current.trim() ||
        HEADING.test(current) ||
        HR.test(current) ||
        /^\s*```/.test(current) ||
        /^\s*&gt;\s?/.test(current) ||
        UL_ITEM.test(current) ||
        OL_ITEM.test(current) ||
        (current.includes("|") &&
          index + 1 < lines.length &&
          TABLE_DIVIDER.test(lines[index + 1]))
      ) {
        break;
      }
      paragraph.push(inline(current));
      index += 1;
    }
    html.push(`<p>${paragraph.join("<br />")}</p>`);
  }

  return html.join("\n");
}
